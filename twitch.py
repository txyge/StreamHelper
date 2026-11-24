"""Клиент Twitch Helix, OAuth Device Code и EventSub."""
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import twitch_data as data
from streams import Problem, field

ID = "https://id.twitch.tv/oauth2/"
HELIX = "https://api.twitch.tv/helix/"
EVENTSUB = "wss://eventsub.wss.twitch.tv/ws"
SCOPES = "user:read:chat moderator:read:chatters moderation:read bits:read channel:manage:clips"
PST = timezone(timedelta(hours=-8))


class TwitchError(Problem):
    def __init__(self, status, message=""):
        super().__init__(f"Twitch вернул ошибку HTTP {status}.", 502)
        self.upstream_status = status
        self.reason = message


def fetch(url, headers=None, form=None, body=None):
    if form is not None:
        content = urlencode(form).encode()
    else:
        content = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(url, data=content, headers=headers or {}), timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            reason = json.loads(exc.read()).get("message", "")
        except (ValueError, AttributeError):
            reason = ""
        raise TwitchError(exc.code, reason) from None
    except (URLError, TimeoutError, ValueError):
        raise Problem("Не удалось связаться с Twitch. Проверьте подключение.", 502) from None


class Twitch:
    def __init__(self, store):
        self.store = store
        self.file = store.directory / "twitch-auth.json"
        self.lock = threading.Lock()
        self.pending = False
        self.account = None
        self.credentials = None
        self.ready = False
        self.offline_polls = 0
        self.message = "Twitch не подключён."
        with store.connect(write=True) as db:
            db.executescript(data.SCHEMA)
        if self.file.exists():
            try:
                self.credentials = json.loads(self.file.read_text(encoding="utf-8"))
                self.pending = True
                self.spawn(self.run)
            except (OSError, ValueError):
                self.message = "Не удалось прочитать авторизацию. Подключите Twitch повторно."

    @staticmethod
    def spawn(target, *args):
        threading.Thread(target=target, args=args, daemon=True).start()

    def status(self):
        return {"ready": self.ready, "pending": self.pending, "message": self.message,
                "login": self.account.get("login") if self.account else None}

    def connect(self, client_id):
        if not isinstance(client_id, str) or not re.fullmatch(r"[a-zA-Z0-9]{10,80}", client_id):
            raise Problem("Укажите Client ID зарегистрированного приложения Twitch.")
        try:
            import websocket  # noqa: F401
        except ImportError:
            raise Problem("Установите зависимости Twitch из requirements-twitch.txt.", 503) from None
        with self.lock:
            if self.pending or self.ready:
                raise Problem("Подключение Twitch уже запущено.", 409)
            device = fetch(ID + "device", form={"client_id": client_id, "scopes": SCOPES})
            uri = urlsplit(device["verification_uri"])
            if uri.scheme != "https" or uri.hostname not in {"www.twitch.tv", "twitch.tv", "id.twitch.tv"}:
                raise Problem("Twitch вернул непредвиденный адрес авторизации.", 502)
            self.pending = True
            self.message = "Ожидаем подтверждения в Twitch."
            self.spawn(self.authorize, client_id, device)
        return {"url": device["verification_uri"], "code": device["user_code"]}

    def authorize(self, client_id, device):
        wait = max(1, device["interval"])
        expires = time.monotonic() + device["expires_in"]
        while time.monotonic() < expires:
            time.sleep(wait)
            try:
                tokens = fetch(ID + "token", form={
                    "client_id": client_id, "scopes": SCOPES, "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                })
                self.save(client_id, tokens)
                self.run()
                return
            except TwitchError as exc:
                if exc.reason == "authorization_pending":
                    continue
                if exc.reason == "slow_down":
                    wait += 5
                    continue
            except Problem as exc:
                if exc.status == 502:
                    continue
            except OSError:
                break
            break
        self.pending = False
        self.message = "Авторизация не завершена. Подключите Twitch повторно."

    def save(self, client_id, tokens):
        credentials = {
            "client_id": client_id, "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        }
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(credentials), encoding="utf-8")
        temp.replace(self.file)
        self.credentials = credentials

    def validate(self):
        credentials = self.credentials
        try:
            account = fetch(ID + "validate",
                            {"Authorization": "OAuth " + credentials["access_token"]})
        except TwitchError as exc:
            if exc.upstream_status != 401:
                raise
            self.save(credentials["client_id"], fetch(ID + "token", form={
                "client_id": credentials["client_id"], "grant_type": "refresh_token",
                "refresh_token": credentials["refresh_token"]
            }))
            account = fetch(ID + "validate",
                            {"Authorization": "OAuth " + self.credentials["access_token"]})
        if account["client_id"] != self.credentials["client_id"] or not set(SCOPES.split()).issubset(account["scopes"]):
            raise Problem("В Twitch выданы не все необходимые разрешения. Подключите аккаунт повторно.")
        self.account = account
        self.validate_at = time.monotonic() + min(3500, max(10, account.get("expires_in", 3600) - 30))
        return account["user_id"]

    def helix(self, endpoint, query=None, body=None):
        credentials = self.credentials
        url = HELIX + endpoint
        if query:
            url += "?" + urlencode(query, doseq=True)
        return fetch(url, {
            "Authorization": "Bearer " + credentials["access_token"],
            "Client-Id": credentials["client_id"], "Content-Type": "application/json"
        }, body=body)

    def pages(self, endpoint, **query):
        seen = set()
        while True:
            result = self.helix(endpoint, query)
            yield from result["data"]
            cursor = result.get("pagination", {}).get("cursor")
            if not cursor or cursor in seen:
                return
            seen.add(cursor)
            query["after"] = cursor

    def sync(self, channel):
        live = self.helix("streams", {"user_id": channel})["data"]
        stream = live[0] if live else None
        self.offline_polls = 0 if stream else self.offline_polls + 1
        with self.store.connect(write=True) as db:
            prior = data.active(db, channel)
            if not stream and prior and self.offline_polls < 2:
                return
            sid = data.sync_stream(db, channel, stream)
            recent = db.execute(
                "SELECT s.*, t.stream FROM sessions s JOIN twitch_streams t ON t.session_id=s.id "
                "WHERE t.channel=? ORDER BY s.started DESC LIMIT 1", (channel,)
            ).fetchone()
        if stream and sid is None and (not recent or recent["stream"] != stream["id"]):
            self.message = "Twitch в эфире. Завершите активную демонстрационную сессию."
            return
        self.message = "Эфир Twitch подключён." if sid else "Twitch подключён. Ожидаем трансляцию."
        if sid:
            self.update_audience(channel, sid)

        if recent:
            self.update_pending(channel)
            if sid or time.time() - (recent["ended"] or time.time()) < 900:
                self.update_report(channel, recent)

    def update_audience(self, channel, sid):
        chatters = list(self.pages("chat/chatters", broadcaster_id=channel, moderator_id=channel, first=1000))
        with self.store.connect(write=True) as db:
            for person in chatters:
                data.person(db, sid, person["user_id"], person["user_name"])

    def update_report(self, channel, stream):
        sid = stream["id"]
        moderators = [item["user_name"] for item in self.pages(
            "moderation/moderators", broadcaster_id=channel, first=100
        )]
        with self.store.connect(write=True) as db:
            db.execute("UPDATE twitch_streams SET moderators=? WHERE session_id=?",
                       (json.dumps(moderators, ensure_ascii=False), sid))

        today = datetime.fromtimestamp(stream["ended"] or time.time(), PST).date().isoformat()
        leaderboard = self.helix("bits/leaderboard", {
            "count": 100, "period": "day", "started_at": today + "T00:00:00-08:00"
        })["data"]
        bits = {"date": today, "entries": [
            {"name": item["user_name"], "count": item["score"]} for item in leaderboard
        ]}
        with self.store.connect(write=True) as db:
            db.execute("UPDATE twitch_streams SET bits_today=? WHERE session_id=?",
                       (json.dumps(bits, ensure_ascii=False), sid))
        videos = self.helix("videos", {"user_id": channel, "type": "archive", "first": 10})["data"]
        vods = {v["id"] for v in videos if v.get("stream_id") == stream["stream"]}
        if not vods:
            return
        matches = [item for item in self.pages(
            "clips", broadcaster_id=channel, started_at=data.iso(stream["started"]),
            ended_at=data.iso(max(stream["started"] + 1, stream["ended"] or time.time())), first=100
        ) if item.get("video_id") in vods]
        with self.store.connect(write=True) as db:
            for item in matches:
                data.save_clip(db, sid, item)

    def update_pending(self, channel):
        with self.store.connect() as db:
            pending = dict(db.execute(
                "SELECT c.id,c.session_id FROM twitch_clips c JOIN twitch_streams t "
                "ON t.session_id=c.session_id WHERE t.channel=? AND c.url IS NULL "
                "AND c.created>? LIMIT 100", (channel, time.time() - 86400)
            ).fetchall())
        if pending:
            clips = self.helix("clips", {"id": list(pending)})["data"]
            with self.store.connect(write=True) as db:
                for clip in clips:
                    if clip["id"] in pending:
                        data.save_clip(db, pending[clip["id"]], clip)


    @staticmethod
    def clip_time(value):
        if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9]{1,3}:)?[0-5]?[0-9]:[0-5][0-9]", value.strip()):
            raise Problem("Введите таймкод в формате ММ:СС или ЧЧ:ММ:СС.")
        parts = [int(part) for part in value.strip().split(":")]
        return sum(part * 60**index for index, part in enumerate(reversed(parts)))

    def create_clip(self, sid, fields):
        if not self.ready:
            raise Problem("Сначала подключите Twitch.", 409)
        start = self.clip_time(fields.get("start"))
        end = self.clip_time(fields.get("end"))
        if not 5 <= end - start <= 60:
            raise Problem("Конец должен быть позже начала на 5–60 секунд.")
        title = field(fields, "title", 100, required=False)
        channel = self.account["user_id"]
        with self.store.connect() as db:
            stream = db.execute(
                "SELECT s.title, t.stream FROM sessions s JOIN twitch_streams t ON t.session_id=s.id "
                "WHERE t.session_id=? AND t.channel=?", (sid, channel)
            ).fetchone()
        if not stream:
            raise Problem("Выберите эфир подключённого канала Twitch.", 409)

        vod = next((video for video in self.pages("videos", user_id=channel, type="archive", first=100)
                    if video.get("stream_id") == stream["stream"]), None)
        if vod is None:
            raise Problem("Архив этого эфира ещё недоступен. Включите сохранение трансляций в Twitch и дождитесь появления записи.", 409)
        match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", vod.get("duration", ""))
        if match and vod.get("duration"):
            hours, minutes, seconds = (int(value or 0) for value in match.groups())
            if end > hours * 3600 + minutes * 60 + seconds:
                raise Problem("Конец клипа выходит за доступную часть архива Twitch. Подождите или укажите более ранний таймкод.", 409)
        try:
            result = self.helix("videos/clips", {
                "broadcaster_id": channel, "editor_id": channel, "vod_id": vod["id"],
                "vod_offset": end, "duration": end - start,
                "title": title or stream["title"][:100] or "Момент эфира",
            }, body={})["data"][0]
        except TwitchError as exc:
            if exc.upstream_status == 403:
                raise Problem("Twitch запретил создание клипа. Проверьте настройки клипов канала.", 403) from None
            if exc.upstream_status == 404:
                raise Problem("Архив ещё недоступен для создания клипа на Twitch.", 409) from None
            raise
        with self.store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO twitch_clips(id,session_id,created) VALUES (?,?,?)",
                       (result["id"], sid, time.time()))
        return {"id": result["id"]}

    def subscribe(self, channel, session):
        for kind in ("channel.chat.message", "stream.online", "stream.offline", "channel.cheer"):
            condition = {"broadcaster_user_id": channel}
            if kind == "channel.chat.message":
                condition["user_id"] = channel
            self.helix("eventsub/subscriptions", body={
                "type": kind, "version": "1", "condition": condition,
                "transport": {"method": "websocket", "session_id": session}
            })

    def notification(self, channel, message):
        meta = message["metadata"]
        kind = meta["subscription_type"]
        event = message["payload"]["event"]
        occurred = data.timestamp(meta["message_timestamp"])
        if kind == "stream.online":
            self.offline_polls = 0
            details = self.helix("channels", {"broadcaster_id": channel})["data"]
            if details:
                with self.store.connect(write=True) as db:
                    data.sync_stream(db, channel, {**details[0], **event}, occurred)
        elif kind == "stream.offline":
            with self.store.connect(write=True) as db:
                current = data.active(db, channel)
                if current and current["started"] <= occurred:
                    data.sync_stream(db, channel, None, occurred)
        else:
            with self.store.connect(write=True) as db:
                data.receive(db, channel, kind, meta["message_id"], occurred, event)

    def listen(self, ws_module, channel):
        url = EVENTSUB
        socket = ws_module.create_connection(url, timeout=8)
        try:
            welcome = json.loads(socket.recv())["payload"]["session"]
            self.subscribe(channel, welcome["id"])
            self.ready = True
            next_sync = 0
            keepalive = welcome.get("keepalive_timeout_seconds") or 10
            last_message = time.monotonic()
            socket.settimeout(1)
            while True:
                now = time.monotonic()
                if now >= self.validate_at:
                    self.validate()
                if now >= next_sync:
                    try:
                        self.sync(channel)
                    except Problem as exc:
                        self.message = str(exc)
                    next_sync = time.monotonic() + 25
                    last_message = time.monotonic()
                try:
                    message = json.loads(socket.recv())
                except ws_module.WebSocketTimeoutException:
                    if time.monotonic() - last_message > keepalive + 5:
                        raise ConnectionError
                    continue
                last_message = time.monotonic()
                kind = message["metadata"]["message_type"]
                if kind == "notification":
                    self.notification(channel, message)
                    if message["metadata"]["subscription_type"].startswith("stream."):
                        next_sync = 0
                elif kind == "session_reconnect":
                    target = message["payload"]["session"]["reconnect_url"]
                    parsed = urlsplit(target)
                    if parsed.scheme != "wss" or parsed.hostname != urlsplit(EVENTSUB).hostname:
                        raise ConnectionError
                    replacement = ws_module.create_connection(target, timeout=8)
                    try:
                        json.loads(replacement.recv())["payload"]["session"]
                    except Exception:
                        replacement.close()
                        raise
                    socket.close()
                    socket = replacement
                    socket.settimeout(1)
                elif kind == "revocation":
                    raise Problem("Twitch отозвал доступ. Подключите аккаунт повторно.", 403)
        finally:
            socket.close()

    def run(self):
        try:
            import websocket
        except ImportError:
            self.message = "Для Twitch установите requirements-twitch.txt и перезапустите сервер."
            self.pending = False
            return
        try:
            while True:
                try:
                    channel = self.validate()
                    self.listen(websocket, channel)
                except TwitchError as exc:
                    self.message = str(exc)
                    if exc.upstream_status in (400, 401, 403):
                        self.message += " Подключите аккаунт повторно."
                        return
                except Problem as exc:
                    self.message = str(exc)
                    if exc.status != 502:
                        return
                except (OSError, ValueError, KeyError, websocket.WebSocketException):
                    self.message = "Связь с Twitch прервана. Повторяем подключение."
                finally:
                    self.ready = False
                time.sleep(8)
        finally:
            self.pending = False
