"""Сессии, таймкоды и локальное хранилище."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def field(values, key, limit, required=True):
    value = values.get(key, "")
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise Problem(f"Допустимо до {limit} символов в поле «{key}».")
    value = value.strip()
    if required and not value:
        raise Problem("Заполните обязательные поля.")
    return value


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / "streamhelper.sqlite"
        with self.connect() as db:
            db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.file, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()


def session(db, sid, live=False):
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        raise Problem("Эфир не найден.", 404)
    if live and row["ended"] is not None:
        raise Problem("Эфир уже завершён.", 409)
    return row


def duration(row):
    end = row["ended"] if row["ended"] is not None else time.time()
    return max(0, int(end - row["started"]))


def start(db, data):
    if db.execute("SELECT 1 FROM sessions WHERE ended IS NULL").fetchone():
        raise Problem("Сначала завершите активный эфир.", 409)
    title = field(data, "title", 120)
    sid = db.execute("INSERT INTO sessions(title, started) VALUES (?, ?)",
                     (title, time.time())).lastrowid
    return {"id": sid}


def finish(db, sid, data):
    row = session(db, sid, live=True)
    db.execute("UPDATE sessions SET ended = ? WHERE id = ?",
               (max(time.time(), row["started"]), sid))
    return {"id": sid}


def mark(db, sid, data):
    row = session(db, sid, live=True)
    label = field(data, "label", 120)
    note = field(data, "note", 500, required=False)
    seconds = duration(row)
    mid = db.execute(
        "INSERT INTO marks(session_id, seconds, label, note) VALUES (?, ?, ?, ?)",
        (sid, seconds, label, note)
    ).lastrowid
    return {"id": mid, "seconds": seconds}


def rows(db, query, sid):
    return [dict(row) for row in db.execute(query, (sid,))]


def detail(db, sid):
    row = session(db, sid)
    return {
        "session": dict(row), "duration": duration(row),
        "marks": rows(db, "SELECT * FROM marks WHERE session_id=? ORDER BY id", sid),
    }
