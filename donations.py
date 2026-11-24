"""OAuth DonationAlerts и синхронизация истории платежей."""
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from streams import Problem, session

BASE = "https://www.donationalerts.com"
SCOPE = "oauth-donation-index"
SCHEMA = """
CREATE TABLE IF NOT EXISTS session_donations (
    session_id INTEGER NOT NULL REFERENCES sessions,
    id TEXT NOT NULL, occurred REAL NOT NULL, name TEXT NOT NULL,
    amount TEXT NOT NULL, currency TEXT NOT NULL,
    PRIMARY KEY (session_id,id)
);
CREATE TABLE IF NOT EXISTS donation_sync (
    session_id INTEGER PRIMARY KEY REFERENCES sessions, fetched_at REAL NOT NULL
);
"""


def fetch(path, token=None, form=None):
    headers = {"Accept":"application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = urlencode(form).encode() if form is not None else None
    with urlopen(Request(BASE + path, data=data, headers=headers), timeout=10) as response:
        return json.load(response)


class Donations:
    def __init__(self, store, port):
        self.store = store
        self.client = os.getenv("DA_CLIENT_ID", "")
        self.secret = os.getenv("DA_CLIENT_SECRET", "")
        self.offset = timezone(timedelta(minutes=int(os.getenv("DA_UTC_OFFSET_MINUTES", "0"))))
        self.redirect = f"http://127.0.0.1:{port}/donationalerts/callback"
        self.path = store.directory / "donationalerts-auth.json"
        self.lock = threading.Lock()
        self.pending = {}
        self.tokens = {}
        if self.path.is_file():
            try:
                self.tokens = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if os.getenv("DA_ACCESS_TOKEN"):
            self.tokens = {"access_token":os.environ["DA_ACCESS_TOKEN"]}
        self.message = ""
        with store.connect() as db:
            db.executescript(SCHEMA)

    def status(self):
        return {"configured": bool(self.client and self.secret), "connected": bool(self.tokens),
                "message": self.message}

    def authorization(self):
        if not self.client or not self.secret:
            raise Problem("Задайте DA_CLIENT_ID и DA_CLIENT_SECRET перед запуском.")
        with self.lock:
            state = secrets.token_urlsafe(32)
            now = time.monotonic()
            self.pending = {key:value for key,value in self.pending.items() if value > now}
            self.pending[state] = now + 600
        return BASE + "/oauth/authorize?" + urlencode({
            "client_id":self.client, "redirect_uri":self.redirect, "response_type":"code",
            "scope":SCOPE, "state":state,
        })

    def callback(self, query):
        with self.lock:
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            if self.pending.pop(state, 0) <= time.monotonic() or not code:
                raise Problem("Авторизация DonationAlerts отменена или устарела.")
            self.exchange({"grant_type":"authorization_code", "code":code, "redirect_uri":self.redirect})
            self.message = ""

    def exchange(self, fields):
        try:
            tokens = fetch("/oauth/token", form={"client_id":self.client, "client_secret":self.secret, **fields})
            if not tokens.get("access_token"):
                raise ValueError
        except (URLError, ValueError):
            raise Problem("DonationAlerts отклонил авторизацию. Проверьте настройки приложения.", 502) from None
        temp = self.path.with_suffix(".tmp")
        updated = {**self.tokens, **tokens}
        temp.write_text(json.dumps(updated), encoding="utf-8")
        temp.replace(self.path)
        self.tokens = updated

    def sync_later(self, sid):
        if self.tokens:
            threading.Thread(target=self.sync_finished, args=(sid,), daemon=True).start()

    def sync_finished(self, sid):
        try:
            self.sync(sid)
        except Problem as exc:
            self.message = str(exc)

    def sync(self, sid):
        with self.lock:
            if not self.tokens:
                raise Problem("Сначала подключите DonationAlerts.", 409)
            with self.store.connect() as db:
                row = session(db, sid)
                start, end = row["started"], row["ended"] or time.time()
            try:
                contents = self.read_history(start, end)
            except HTTPError as exc:
                if exc.code != 401 or not self.tokens.get("refresh_token") or not self.client or not self.secret:
                    raise Problem("Не удалось получить историю DonationAlerts. Проверьте подключение.", 502) from None
                self.exchange({"grant_type":"refresh_token", "scope":SCOPE,
                               "refresh_token":self.tokens["refresh_token"]})
                try:
                    contents = self.read_history(start, end)
                except (URLError, ValueError, KeyError, TypeError):
                    raise Problem("Не удалось получить историю DonationAlerts.", 502) from None
            except (URLError, ValueError, KeyError, TypeError):
                raise Problem("Не удалось получить историю DonationAlerts.", 502) from None
            with self.store.connect(write=True) as db:
                db.execute("DELETE FROM session_donations WHERE session_id=?", (sid,))
                db.executemany("INSERT OR REPLACE INTO session_donations VALUES (?,?,?,?,?,?)",
                               ((sid, *row) for row in contents))
                db.execute("INSERT OR REPLACE INTO donation_sync VALUES (?,?)", (sid,time.time()))
            self.message = ""

    def read_history(self, start, end):
        result = []
        page = 1
        while True:
            payload = fetch(f"/api/v1/alerts/donations?page={page}", self.tokens["access_token"])
            for item in payload["data"]:
                raw = item["created_at"]
                normalized = raw.replace("Z", "+00:00")
                if len(normalized) >= 19 and normalized[13] == normalized[16] == ".":
                    normalized = normalized[:11] + normalized[11:19].replace(".", ":") + normalized[19:]
                date = datetime.fromisoformat(normalized)
                at = (date if date.tzinfo else date.replace(tzinfo=self.offset)).timestamp()
                if start <= at <= end:
                    result.append((str(item["id"]),at,item.get("username") or "Анонимно",
                                   str(item["amount"]),item["currency"]))
            if not (payload.get("links") or {}).get("next"):
                return result
            page += 1
