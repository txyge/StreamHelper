"""Данные эфира Twitch и построение публичной сводки."""
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from chat import add_question, question_text
from streams import duration

SCHEMA = """
CREATE TABLE IF NOT EXISTS twitch_streams (
    session_id INTEGER PRIMARY KEY REFERENCES sessions,
    channel TEXT NOT NULL, stream TEXT NOT NULL UNIQUE,
    categories TEXT NOT NULL DEFAULT '[]', moderators TEXT, bits_today TEXT
);
CREATE TABLE IF NOT EXISTS twitch_people (
    session_id INTEGER NOT NULL REFERENCES sessions, user_id TEXT NOT NULL,
    name TEXT NOT NULL, messages INTEGER NOT NULL DEFAULT 0, bits INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, user_id)
);
CREATE TABLE IF NOT EXISTS twitch_events (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS twitch_clips (
    id TEXT PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions,
    title TEXT, url TEXT, created REAL NOT NULL
);
"""


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def active(db, channel):
    return db.execute(
        "SELECT s.*, t.stream FROM sessions s JOIN twitch_streams t ON t.session_id=s.id "
        "WHERE t.channel=? AND s.ended IS NULL", (channel,)
    ).fetchone()


def sync_stream(db, channel, stream, now=None):
    now = time.time() if now is None else now
    previous = active(db, channel)
    if previous and (not stream or previous["stream"] != stream["id"]):
        end = timestamp(stream["started_at"]) if stream else now
        db.execute("UPDATE sessions SET ended=? WHERE id=?",
                   (max(previous["started"], end), previous["id"]))
    if not stream:
        return None
    existing = db.execute(
        "SELECT s.*, t.categories FROM twitch_streams t JOIN sessions s ON s.id=t.session_id "
        "WHERE t.stream=? AND t.channel=?", (stream["id"], channel)
    ).fetchone()
    if existing:
        sid = existing["id"]
        # A stale polling result must not reopen an ended broadcast.
        if existing["ended"] is not None:
            return None
        categories = json.loads(existing["categories"])
    else:
        if db.execute("SELECT 1 FROM sessions WHERE ended IS NULL").fetchone():
            return None
        sid = db.execute("INSERT INTO sessions(title, started) VALUES (?,?)",
                         (stream["title"], timestamp(stream["started_at"]))).lastrowid
        db.execute("INSERT INTO twitch_streams(session_id,channel,stream) VALUES (?,?,?)",
                   (sid, channel, stream["id"]))
        categories = []
    category = stream.get("game_name")
    if category and (not categories or categories[-1] != category):
        categories.append(category)
    db.execute("UPDATE sessions SET title=? WHERE id=?", (stream["title"], sid))
    db.execute("UPDATE twitch_streams SET categories=? WHERE session_id=?",
               (json.dumps(categories, ensure_ascii=False), sid))
    return sid


def person(db, sid, user_id, name, messages=0, bits=0):
    db.execute(
        "INSERT INTO twitch_people VALUES (?,?,?,?,?) ON CONFLICT(session_id,user_id) DO UPDATE "
        "SET name=excluded.name, messages=messages+excluded.messages, bits=bits+excluded.bits",
        (sid, user_id, name, messages, bits)
    )


def receive(db, channel, kind, event_id, occurred, event):
    if event.get("broadcaster_user_id") != channel:
        return
    row = db.execute(
        "SELECT s.id FROM sessions s JOIN twitch_streams t ON t.session_id=s.id "
        "WHERE t.channel=? AND s.started<=? AND (s.ended IS NULL OR s.ended>=?) "
        "ORDER BY s.started DESC LIMIT 1", (channel, occurred, occurred)
    ).fetchone()
    if row is None:
        return
    sid = row["id"]
    if not db.execute("INSERT OR IGNORE INTO twitch_events VALUES (?)", (event_id,)).rowcount:
        return
    if kind == "channel.chat.message":
        name = event["chatter_user_name"]
        person(db, sid, event["chatter_user_id"], name, messages=1)
        body = event["message"]["text"].strip()
        if question_text(body):
            mid = db.execute("INSERT INTO messages(session_id,nick,body) VALUES (?,?,?)",
                             (sid, name, body)).lastrowid
            add_question(db, sid, mid, name, body)
    elif kind == "channel.cheer":
        key = event.get("user_id") or "anonymous"
        name = event.get("user_name") or "Анонимно"
        person(db, sid, key, name, bits=event["bits"])


def save_clip(db, sid, item):
    url = item.get("url")
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or parsed.hostname not in {"clips.twitch.tv", "www.twitch.tv"}:
        return
    db.execute(
        "INSERT INTO twitch_clips VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE "
        "SET title=excluded.title,url=excluded.url,created=excluded.created "
        "WHERE twitch_clips.session_id=excluded.session_id",
        (item["id"], sid, item["title"], url, timestamp(item["created_at"]))
    )


def card(db, sid):
    row = db.execute(
        "SELECT s.*, t.categories, t.moderators, t.bits_today "
        "FROM sessions s JOIN twitch_streams t ON t.session_id=s.id WHERE s.id=?", (sid,)
    ).fetchone()
    if row is None:
        return None
    people = [dict(p) for p in db.execute(
        "SELECT name,messages,bits,user_id FROM twitch_people WHERE session_id=? "
        "ORDER BY name COLLATE NOCASE,user_id", (sid,)
    )]
    clips = [dict(c) for c in db.execute(
        "SELECT title,url FROM twitch_clips WHERE session_id=? AND url IS NOT NULL "
        "ORDER BY created,id", (sid,)
    )]
    active_people = sorted((p for p in people if p["messages"]), key=lambda p: -p["messages"])
    donors = sorted((p for p in people if p["bits"]), key=lambda p: -p["bits"])
    return {
        "source": "twitch", "duration": duration(row), "title": row["title"],
        "categories": list(dict.fromkeys(json.loads(row["categories"]))),
        "audience": [p["name"] for p in people if p["user_id"] != "anonymous"],
        "active_chat": [{"name": p["name"], "count": p["messages"]} for p in active_people[:10]],
        "top_bits": [{"name": p["name"], "count": p["bits"]} for p in donors[:10]],
        "bits_today": json.loads(row["bits_today"]) if row["bits_today"] is not None else None,
        "moderators": json.loads(row["moderators"]) if row["moderators"] is not None else None,
        "clips": clips,
    }
