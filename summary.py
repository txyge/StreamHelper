"""Единый итог сессии, доступный в локальной панели."""
from datetime import datetime, timezone
import time

from streams import duration, session, rows


def detail(db, sid):
    row = session(db, sid)
    people = rows(db, "SELECT name,moderator FROM bot_people WHERE session_id=? ORDER BY name COLLATE NOCASE", sid)
    end = row["ended"] if row["ended"] is not None else time.time()
    synced = db.execute("SELECT fetched_at FROM donation_sync WHERE session_id=?", (sid,)).fetchone()
    donations = db.execute(
        "SELECT occurred,name,amount,currency FROM session_donations WHERE session_id=? AND occurred BETWEEN ? AND ? ORDER BY occurred,id",
        (sid, row["started"], end)
    )
    return {
        "session_id":sid, "title":row["title"], "duration":duration(row),
        "started_at":row["started"], "ended_at":row["ended"],
        "topics":rows(db, "SELECT occurred,category,title FROM bot_topics WHERE session_id=? ORDER BY occurred", sid),
        "viewers":[p["name"] for p in people],
        "moderators":[p["name"] for p in people if p["moderator"]],
        "donations":[dict(item) for item in donations],
        "donations_synced":synced["fetched_at"] if synced else None,
    }


def credits(report):
    def utc(seconds):
        return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    hours, seconds = divmod(report["duration"], 3600)
    minutes, seconds = divmod(seconds, 60)
    duration_text = f"{hours:02}:{minutes:02}:{seconds:02}"
    items = [report["title"], f"Длительность: {duration_text}",
             f"Начало: {utc(report['started_at'])}"]
    if report["ended_at"] is not None:
        items.append(f"Завершение: {utc(report['ended_at'])}")

    sections = [
        ("Категории и темы", [" · ".join(filter(None, (utc(t["occurred"]), t["category"], t["title"])))
                             for t in report["topics"]], "Категории и названия не получены."),
        ("Обнаруженные зрители", report["viewers"], "Никого не обнаружено."),
        ("Модераторы на эфире", report["moderators"], "Модераторы не обнаружены."),
        ("Донаты за эфир", [f'{utc(d["occurred"])} · {d["name"]} · {d["amount"]} {d["currency"]}'
                            for d in report["donations"]],
         "За этот интервал донатов нет." if report["donations_synced"] else "Данные пока недоступны."),
    ]
    for heading, values, empty in sections:
        items.extend(["", heading, *(values or [empty])])
    if report["donations_synced"]:
        items.append("История обновлена: " + utc(report["donations_synced"]))
    return "\n".join(items) + "\n"
