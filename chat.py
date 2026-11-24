"""Демонстрационный чат, очередь вопросов и модерация."""
import json

from streams import Problem, field, rows, session


def add_question(db, sid, message_id, nick, body):
    parts = body.split(maxsplit=1)
    if len(parts) == 2 and parts[0].casefold() == "!вопрос":
        db.execute(
            "INSERT OR IGNORE INTO questions(session_id, message_id, nick, body) VALUES (?, ?, ?, ?)",
            (sid, message_id, nick, parts[1])
        )


def message(db, sid, data):
    session(db, sid, live=True)
    nick = field(data, "nick", 40)
    body = field(data, "body", 500)
    settings = db.execute("SELECT phrases FROM rules WHERE session_id=?", (sid,)).fetchone()
    phrases = json.loads(settings["phrases"]) if settings else []
    matched = next((phrase for phrase in phrases if phrase.casefold() in body.casefold()), None)
    mid = db.execute(
        "INSERT INTO messages(session_id, nick, body, rule) VALUES (?, ?, ?, ?)",
        (sid, nick, body, matched)
    ).lastrowid
    if matched is None:
        add_question(db, sid, mid, nick, body)
    return {"id": mid, "hidden": matched is not None}


def restore(db, sid, data):
    mid = item_id(data, "id")
    item = db.execute(
        "SELECT * FROM messages WHERE id=? AND session_id=? AND rule IS NOT NULL",
        (mid, sid)
    ).fetchone()
    if not item:
        raise Problem("Скрытое сообщение не найдено.", 404)
    db.execute("UPDATE messages SET restored=1 WHERE id=?", (mid,))
    add_question(db, sid, mid, item["nick"], item["body"])
    return {"id": mid}


def item_id(data, key):
    value = data.get(key)
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise Problem("Некорректный идентификатор.")
    return value


def answer(db, sid, data):
    qid = item_id(data, "id")
    count = db.execute("UPDATE questions SET answered=1 WHERE id=? AND session_id=?",
                       (qid, sid)).rowcount
    if not count:
        raise Problem("Вопрос не найден.", 404)
    return {"id": qid}


def settings(db, sid, data):
    session(db, sid, live=True)
    game = field(data, "game", 100)
    raw = field(data, "phrases", 3000, required=False)
    phrases = list(dict.fromkeys(line.strip() for line in raw.splitlines() if line.strip()))
    db.execute(
        "INSERT INTO rules VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE "
        "SET game=excluded.game, phrases=excluded.phrases",
        (sid, game, json.dumps(phrases, ensure_ascii=False))
    )
    return {"game": game, "phrases": phrases}


def detail(db, sid):
    messages = rows(db, "SELECT * FROM messages WHERE session_id=? ORDER BY id", sid)
    hidden = [m for m in messages if m["rule"] and not m["restored"]]
    row = db.execute("SELECT * FROM rules WHERE session_id=?", (sid,)).fetchone()
    return {
        "messages": [m for m in messages if not m["rule"] or m["restored"]],
        "hidden": hidden,
        "flagged_count": sum(m["rule"] is not None for m in messages),
        "questions": rows(db, "SELECT * FROM questions WHERE session_id=? ORDER BY id", sid),
        "settings": {"game": row["game"], "phrases": json.loads(row["phrases"])}
                    if row else {"game": "", "phrases": []},
    }
