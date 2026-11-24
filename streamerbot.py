"""События Twitch, полученные через локальный Streamer.bot."""
import base64
import hashlib
import json
import os
import threading
import time
from datetime import datetime

from chat import add_question, question_text

EVENTS = ["StreamOnline", "StreamOffline", "StreamUpdate", "StreamUpdateGameOnConnect",
          "ChatMessage", "PresentViewers", "UserBanned", "UserTimedOut",
          "UserUnbanned", "UserUntimedOut", "ChatMessageDeleted", "WarnedUser"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_streams (
    session_id INTEGER PRIMARY KEY REFERENCES sessions, external_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS bot_people (
    session_id INTEGER NOT NULL REFERENCES sessions, user_id TEXT NOT NULL,
    name TEXT NOT NULL, moderator INTEGER NOT NULL,
    PRIMARY KEY (session_id, user_id)
);
CREATE TABLE IF NOT EXISTS bot_topics (
    session_id INTEGER NOT NULL REFERENCES sessions, occurred REAL NOT NULL,
    category TEXT NOT NULL, title TEXT NOT NULL,
    PRIMARY KEY (session_id, occurred, category, title)
);
CREATE TABLE IF NOT EXISTS bot_messages (id TEXT PRIMARY KEY);
"""


def stamp(value, fallback):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.timestamp() if date.tzinfo else fallback
    except (AttributeError, ValueError):
        return fallback


def presence(db, sid, user, moderator=False):
    key = user.get("id") or user.get("login")
    name = user.get("name") or user.get("displayName") or user.get("display") or user.get("login")
    if not key or not name:
        return
    badges = user.get("badges") or []
    moderator = moderator or user.get("isModerator") is True or str(user.get("role")).casefold() in {"moderator", "leadmoderator"} or any(
        (badge.get("name") or badge.get("set_id")) in {"moderator", "lead_moderator", "lead-moderator"}
        for badge in badges if isinstance(badge, dict)
    )
    db.execute(
        "INSERT INTO bot_people VALUES (?,?,?,?) ON CONFLICT(session_id,user_id) DO UPDATE "
        "SET name=excluded.name,moderator=max(moderator,excluded.moderator)",
        (sid, str(key), name, int(moderator))
    )


class StreamerBot:
    def __init__(self, store, on_finish):
        self.store = store
        self.on_finish = on_finish
        self.url = os.getenv("STREAMERBOT_WS", "ws://127.0.0.1:8080/")
        self.password = os.getenv("STREAMERBOT_PASSWORD", "")
        self.message = "Ожидаем локальный Streamer.bot."
        self.category = ""
        self.title = ""
        with store.connect() as db:
            db.executescript(SCHEMA)

    def start(self):
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        try:
            import websocket
        except ImportError:
            self.message = "Установите зависимость из requirements-twitch.txt."
            return
        while True:
            try:
                connection = websocket.create_connection(self.url, timeout=5)
                try:
                    self.subscribe(connection)

                    connection.settimeout(4)
                    self.message = "Streamer.bot подключён."
                    next_viewers = 0
                    while True:
                        if time.monotonic() >= next_viewers:
                            connection.send(json.dumps({"request":"GetActiveViewers", "id":"viewers"}))
                            next_viewers = time.monotonic() + 50
                        try:
                            message = json.loads(connection.recv())
                        except websocket.WebSocketTimeoutException:
                            continue
                        if message.get("id") == "viewers" and message.get("status") == "ok":
                            self.viewers(message.get("viewers") or [])
                        else:
                            self.event(message)
                finally:
                    connection.close()
            except (OSError, ValueError, TypeError, KeyError, websocket.WebSocketException):
                self.message = "Нет связи со Streamer.bot. Проверьте WebSocket Server."
            time.sleep(5)

    def subscribe(self, connection):
        hello = json.loads(connection.recv())
        authentication = hello.get("authentication")
        if authentication:
            def digest(value):
                return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()
            secret = digest(self.password + authentication["salt"])
            connection.send(json.dumps({"request":"Authenticate", "id":"auth",
                                        "authentication":digest(secret + authentication["challenge"])}))
            if json.loads(connection.recv()).get("status") != "ok":
                raise ValueError("Streamer.bot authentication")
        connection.send(json.dumps({"request":"Subscribe", "id":"streams", "events":{"Twitch":EVENTS}}))
        while True:
            response = json.loads(connection.recv())
            if response.get("id") == "streams":
                if response.get("status") != "ok":
                    raise ValueError("Streamer.bot subscription")
                return
            self.event(response)

    def viewers(self, users):
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT id,started FROM sessions WHERE ended IS NULL").fetchone()
            if row:
                for user in users:
                    if str(user.get("type")).lower() == "twitch" and stamp(
                        user.get("previousActive"), time.time()
                    ) >= row["started"]:
                        presence(db, row["id"], user)

    def event(self, envelope):
        event = envelope.get("event") or {}
        payload = envelope.get("data") or {}
        if event.get("source") != "Twitch" or payload.get("isTest") or payload.get("isFromSharedChatGuest"):
            return
        kind = event.get("type")
        if kind not in EVENTS:
            return
        at = stamp(envelope.get("timeStamp") or envelope.get("timestamp"), time.time())
        at = stamp(payload.get("createdAt"), at)
        ended = None
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT * FROM sessions WHERE ended IS NULL").fetchone()
            if kind in {"StreamOnline", "StreamUpdate", "StreamUpdateGameOnConnect"}:
                game = payload.get("game") or {}
                self.category = game.get("name") or game.get("Name") or self.category
                self.title = payload.get("status") or payload.get("title") or self.title
                if kind == "StreamOnline":
                    external_id = payload.get("id")
                    if external_id and db.execute("SELECT 1 FROM bot_streams WHERE external_id=?", (external_id,)).fetchone():
                        return
                    started = stamp(payload.get("startedAt"), at)
                    if row and started == row["started"] and db.execute(
                        "SELECT 1 FROM bot_streams WHERE session_id=?", (row["id"],)
                    ).fetchone():
                        return
                    if row and db.execute("SELECT 1 FROM bot_streams WHERE session_id=?", (row["id"],)).fetchone():
                        db.execute("UPDATE sessions SET ended=max(started,?) WHERE id=?", (started, row["id"]))
                        ended = row["id"]
                        row = None
                    if row is None:
                        sid = db.execute("INSERT INTO sessions(title,started) VALUES (?,?)",
                                         (self.title or "Прямой эфир Twitch", started)).lastrowid
                    else:
                        sid = row["id"]
                        db.execute("UPDATE sessions SET started=min(started,?) WHERE id=?", (started, sid))
                    db.execute("INSERT INTO bot_streams VALUES (?,?)", (sid, external_id))
                    self.topic(db, sid, started)
                elif row and at >= row["started"]:
                    self.topic(db, row["id"], at)
            elif row and at >= row["started"]:
                sid = row["id"]
                if kind == "StreamOffline":
                    db.execute("UPDATE sessions SET ended=? WHERE id=?", (at, sid))
                    ended = sid
                elif kind == "ChatMessage":
                    self.message_event(db, sid, payload)
                elif kind == "PresentViewers":
                    for user in payload.get("viewers") or payload.get("users") or ():
                        if isinstance(user, dict):
                            presence(db, sid, user)
                else:
                    moderator = payload.get("moderator")
                    owner = (payload.get("broadcaster") or {}).get("id")
                    if moderator and moderator.get("id") != owner:
                        presence(db, sid, moderator, moderator=True)
        if ended is not None:
            self.on_finish(ended)

    def topic(self, db, sid, at):
        if self.title:
            db.execute("UPDATE sessions SET title=? WHERE id=?", (self.title, sid))
        if self.category or self.title:
            previous = db.execute(
                "SELECT category,title FROM bot_topics WHERE session_id=? ORDER BY occurred DESC LIMIT 1", (sid,)
            ).fetchone()
            if previous is None or tuple(previous) != (self.category, self.title):
                db.execute("INSERT OR IGNORE INTO bot_topics VALUES (?,?,?,?)",
                           (sid, at, self.category, self.title))

    def message_event(self, db, sid, payload):
        user = payload.get("user") or {}
        if not user:
            return
        presence(db, sid, user)
        text = payload.get("text") or ""
        if not question_text(text):
            return
        identity = payload.get("messageId")
        if identity and not db.execute("INSERT OR IGNORE INTO bot_messages VALUES (?)", (identity,)).rowcount:
            return
        name = user.get("name") or user.get("login") or "Зритель"
        mid = db.execute("INSERT INTO messages(session_id,nick,body) VALUES (?,?,?)",
                         (sid, name, text)).lastrowid
        add_question(db, sid, mid, name, text)
