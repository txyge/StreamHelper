"""Предпросмотр и публикация сформированных итогов."""
import json

import twitch_data
from streams import Problem, duration, session


def preview(db, sid):
    row = session(db, sid)
    card = twitch_data.card(db, sid)
    if card is not None:
        return card
    clips = [{"title": f"{clip['start']:.1f}–{clip['end']:.1f} с",
              "url": "/clips/" + clip["id"]}
             for clip in db.execute("SELECT id,start,end FROM clips WHERE session_id=? ORDER BY rowid", (sid,))]
    return {"source": "demo", "title": row["title"], "duration": duration(row), "clips": clips}


def publish(db, sid, data):
    if session(db, sid)["ended"] is None:
        raise Problem("Дождитесь завершения эфира.", 409)
    card = preview(db, sid)
    db.execute(
        "INSERT INTO published VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
        (json.dumps(card, ensure_ascii=False),)
    )
    return card


def latest(db):
    row = db.execute("SELECT payload FROM published WHERE id=1").fetchone()
    return json.loads(row["payload"]) if row else None
