"""Единый итог сессии, доступный в локальной панели."""
from streams import duration, session, rows
import time


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
        "title":row["title"], "duration":duration(row),
        "topics":rows(db, "SELECT occurred,category,title FROM bot_topics WHERE session_id=? ORDER BY occurred", sid),
        "viewers":[p["name"] for p in people],
        "moderators":[p["name"] for p in people if p["moderator"]],
        "donations":[dict(item) for item in donations],
        "donations_synced":synced["fetched_at"] if synced else None,
    }
