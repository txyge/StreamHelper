"""Снимок выбранных зрительских итогов."""
import json

from chat import item_id
from streams import Problem, duration, field, session


def selected(db, sid, data, key, query):
    if data.get(key) is None:
        return None
    row = db.execute(query, (item_id(data, key), sid)).fetchone()
    if not row:
        raise Problem("Выбранный элемент недоступен в этом эфире.")
    return dict(row)


def publish(db, sid, data):
    row = session(db, sid)
    if row["ended"] is None:
        raise Problem("Сначала завершите эфир.", 409)
    card = {"duration": duration(row)}
    moment = selected(db, sid, data, "moment",
                      "SELECT seconds, label FROM marks WHERE id=? AND session_id=?")
    question = selected(db, sid, data, "question",
                        "SELECT nick, body FROM questions WHERE id=? AND session_id=?")
    if moment is not None:
        card["moment"] = moment
    if question is not None:
        card["question"] = question
    for key in ("challenge", "announcement"):
        text = field(data, key, 250, required=False)
        if text:
            card[key] = text
    db.execute(
        "INSERT INTO published VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
        (json.dumps(card, ensure_ascii=False),)
    )
    return card


def latest(db):
    row = db.execute("SELECT payload FROM published WHERE id=1").fetchone()
    return json.loads(row["payload"]) if row else None
