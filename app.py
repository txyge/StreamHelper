"""Локальный HTTP-сервер проекта."""
import argparse
import json
import os
import re
import socket
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chat
import summary
import streams
from donations import Donations
from streamerbot import StreamerBot
from streams import Problem, ROOT, Store

STATIC = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/help": ("help.html", "text/html"),
    "/summary.js": ("summary.js", "text/javascript"),
    "/mixer.svg": ("mixer.svg", "image/svg+xml"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/style.css": ("style.css", "text/css"),
}
ACTIONS = {
    "finish": streams.finish, "marks": streams.mark,
    "answer": chat.answer,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def handle_request(self, method):
        try:
            host, port = self.server.server_address
            if self.headers.get("Host") not in {f"{host}:{port}", f"localhost:{port}"}:
                raise Problem("Откройте приложение через локальный адрес.", 403)
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin and origin != "http://" + self.headers["Host"]:
                    raise Problem("Разрешены запросы из локальной панели.", 403)
            self.dispatch(method, urlsplit(self.path).path)
        except Problem as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            report_error()
            self.send_json({"error": "Внутренняя ошибка сервера."}, 500)

    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_bytes(data, "application/json; charset=utf-8", status)

    def send_bytes(self, data, mime, status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def length(self, maximum):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise Problem("Некорректный размер запроса.")
        if not 0 < size <= maximum:
            raise Problem("Запрос пуст или превышает допустимый размер.", 413)
        return size

    def json_body(self):
        if self.headers.get_content_type() != "application/json":
            raise Problem("Ожидается JSON.", 415)
        try:
            data = json.loads(self.rfile.read(self.length(32_768)))
        except (ValueError, UnicodeError):
            raise Problem("Некорректный JSON.")
        if not isinstance(data, dict):
            raise Problem("Ожидается объект JSON.")
        return data

    def dispatch(self, method, path):
        store = self.server.store
        if method == "GET" and path == "/api/desktop" and getattr(self.server, "desktop", False):
            self.send_json({"application": "StreamHelper Desktop"})
            return
        if method == "GET" and path == "/api/connections":
            self.send_json({"bot":self.server.bot.message, "donations":self.server.donations.status()})
            return
        if method == "POST" and path == "/api/donationalerts/settings":
            self.send_json(self.server.donations.configure(self.json_body()))
            return
        if method == "GET" and path == "/donationalerts/connect":
            self.redirect(self.server.donations.authorization())
            return
        if method == "GET" and path == "/donationalerts/callback":
            self.server.donations.callback(parse_qs(urlsplit(self.path).query))
            self.redirect("/")
            return
        if method == "GET" and path in STATIC:
            name, mime = STATIC[path]
            content_type = mime if mime.startswith("image/") else mime + "; charset=utf-8"
            self.send_bytes((ROOT / "web" / name).read_bytes(), content_type)
            return
        if path == "/api/sessions":
            with store.connect(write=method == "POST") as db:
                if method == "POST":
                    result = streams.start(db, self.json_body())
                else:
                    result = [dict(row) for row in db.execute("SELECT * FROM sessions ORDER BY id DESC")]
            self.send_json(result)
            return
        match = re.fullmatch(r"/api/sessions/([0-9]+)(?:/([a-z]+))?", path)
        if match:
            sid, action = int(match[1]), match[2]
            if method == "GET" and action in {"summary", "credits"}:
                with store.connect() as db:
                    report = summary.detail(db, sid)
                if action == "credits":
                    self.send_bytes(summary.credits(report).encode("utf-8"), "text/plain; charset=utf-8",
                                    filename=f"stream-{sid}-credits.txt")
                elif parse_qs(urlsplit(self.path).query).get("download") == ["1"]:
                    content = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
                    self.send_bytes(content, "application/json; charset=utf-8", filename=f"stream-{sid}.json")
                else:
                    self.send_json(report)
                return
            if method == "POST" and action == "donations":
                self.json_body()
                self.server.donations.sync(sid)
                self.send_json({"ok": True})
                return
            if method == "GET" and action is None:
                with store.connect() as db:
                    result = {**streams.detail(db, sid), **chat.detail(db, sid),
                              "report": summary.detail(db, sid)}
                self.send_json(result)
                return
            if method == "POST" and action in ACTIONS:
                data = self.json_body()
                with store.connect(write=True) as db:
                    result = ACTIONS[action](db, sid, data)
                if action == "finish":
                    self.server.donations.sync_later(sid)
                self.send_json(result)
                return
        raise Problem("Страница не найдена.", 404)

    def redirect(self, target):
        self.send_response(303)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_request(self, code="-", size="-"):
        if urlsplit(self.path).path != "/donationalerts/callback":
            super().log_request(code, size)


def report_error():
    import traceback
    traceback.print_exc()


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    desktop = getattr(sys, "frozen", False)
    default_data = (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "StreamHelper"
                    if desktop else ROOT / "data")
    parser = argparse.ArgumentParser(description="StreamHelper")
    parser.add_argument("--port", type=int, default=18768 if desktop else 18767)
    parser.add_argument("--data", type=Path, default=default_data)
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    address = f"http://127.0.0.1:{args.port}/"
    try:
        server = LocalServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if not desktop:
            raise
        from urllib.error import URLError
        from urllib.request import urlopen
        try:
            with urlopen(address + "api/desktop", timeout=2) as response:
                existing = json.load(response).get("application") == "StreamHelper Desktop"
        except (URLError, OSError, ValueError):
            existing = False
        if existing and args.data == default_data:
            if not args.no_browser:
                webbrowser.open(address)
            return
        print(f"Could not use {address}. Close the program occupying this port and try again.", file=sys.stderr)
        if sys.stdin.isatty():
            input("Press Enter to close.")
        raise SystemExit(1) from None

    with server:
        server.desktop = desktop
        server.store = Store(args.data)
        server.donations = Donations(server.store, server.server_port)
        server.bot = StreamerBot(server.store, server.donations.sync_later)
        server.bot.start()
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"StreamHelper: {url}", flush=True)
        if desktop and not args.no_browser:
            print("Close this window or press Ctrl+C to stop the server.", flush=True)
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
