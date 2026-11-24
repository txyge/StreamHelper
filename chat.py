"""Очередь вопросов из Twitch."""
from streams import Problem, rows


def question_text(body):
    parts = body.split(maxsplit=1)
    if len(parts) == 2 and parts[0].casefold() == "!вопрос":
        return parts[1]
    return None


def add_question(db, sid, message_id, nick, body):
    question = question_text(body)
    if question:
        db.execute(
            "INSERT OR IGNORE INTO questions(session_id,message_id,nick,body) VALUES (?,?,?,?)",
            (sid, message_id, nick, question)
        )


def answer(db, sid, data):
    qid = data.get("id")
    if type(qid) is not int or not 1 <= qid <= 2**63 - 1:
        raise Problem("Некорректный идентификатор.")
    count = db.execute("UPDATE questions SET answered=1 WHERE id=? AND session_id=?",
                       (qid, sid)).rowcount
    if not count:
        raise Problem("Вопрос не найден.", 404)
    return {"id": qid}


def detail(db, sid):
    return {
        "questions": rows(db, "SELECT * FROM questions WHERE session_id=? ORDER BY id", sid),
    }
