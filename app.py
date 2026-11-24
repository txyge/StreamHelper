"""Локальный HTTP-сервер проекта."""
import argparse
import json
import re
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chat
import media
import publication
import streams
from streams import Problem, ROOT, Store

STATIC = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/viewer": ("viewer.html", "text/html"),
    "/viewer.js": ("viewer.js", "text/javascript"),
    "/card.js": ("card.js", "text/javascript"),
    "/publish.js": ("publish.js", "text/javascript"),
    "/media.js": ("media.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
ACTIONS = {
    "finish": streams.finish, "marks": streams.mark,
    "message": chat.message, "restore": chat.restore,
    "answer": chat.answer, "rules": chat.settings, "publish": publication.publish,
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

    def send_bytes(self, data, mime, status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
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
        if method == "GET" and path == "/api/viewer":
            with store.connect() as db:
                card = publication.latest(db)
            self.send_json(card)
            return
        if method == "GET" and self.find_media(path):
            return
        if method == "GET" and path in STATIC:
            name, mime = STATIC[path]
            self.send_bytes((ROOT / "web" / name).read_bytes(), mime + "; charset=utf-8")
            return
        if path == "/api/sessions":
            with store.connect(write=method == "POST") as db:
                if method == "POST":
                    result = streams.start(db, self.json_body())
                else:
                    result = [dict(row) for row in db.execute(
                        "SELECT * FROM sessions ORDER BY id DESC")]
            self.send_json(result)
            return
        match = re.fullmatch(r"/api/sessions/([0-9]+)(?:/([a-z]+))?", path)
        if match:
            sid, action = int(match[1]), match[2]
            if method == "POST" and action == "recording":
                self.send_json(media.upload(store, sid, self.rfile, self.length(media.MAX_UPLOAD),
                                            self.headers.get_content_type()))
                return
            if method == "POST" and action == "clips":
                self.send_json(media.export(store, sid, self.json_body()))
                return
            if method == "GET" and action is None:
                with store.connect() as db:
                    result = {**streams.detail(db, sid), **chat.detail(db, sid),
                              **media.detail(db, sid)}
                self.send_json(result)
                return
            if method == "POST" and action in ACTIONS:
                data = self.json_body()
                with store.connect(write=True) as db:
                    result = ACTIONS[action](db, sid, data)
                self.send_json(result)
                return
        raise Problem("Страница не найдена.", 404)

    def find_media(self, path):
        store = self.server.store
        if path == "/demo.mp4":
            self.send_file(ROOT / "demo" / "demo.mp4", "video/mp4")
            return True
        match = re.fullmatch(r"/(recordings|clips)/([0-9a-f]{32})", path)
        if not match:
            return False
        kind, key = match.groups()
        with store.connect() as db:
            query = "SELECT mime FROM recordings WHERE id=?" if kind == "recordings" else (
                "SELECT 'video/mp4' AS mime FROM clips WHERE id=?"
            )
            row = db.execute(query, (key,)).fetchone()
        if not row:
            raise Problem("Видео не найдено.", 404)
        name = key if kind == "recordings" else key + ".mp4"
        download = "clip-" + key[:8] + ".mp4" if urlsplit(self.path).query == "download=1" else None
        self.send_file(media.file_path(store, kind, name), row["mime"], download)
        return True

    def send_file(self, path, mime, download=None):
        if not path.is_file():
            raise Problem("Видео не найдено.", 404)
        with path.open("rb") as source:
            size = path.stat().st_size
            first, last = 0, size - 1
            header = self.headers.get("Range")
            if header:
                match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", header)
                if match and match[1]:
                    first = int(match[1])
                    if match[2]:
                        last = min(last, int(match[2]))
                elif match and match[2]:
                    first = max(0, size - int(match[2]))
                else:
                    first = size
                if first > last:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(206 if header else 200)
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(last - first + 1))
            self.send_header("X-Content-Type-Options", "nosniff")
            if header:
                self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            source.seek(first)
            remaining = last - first + 1
            while remaining:
                chunk = source.read(min(remaining, 256 * 1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def report_error():
    import traceback
    traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="СтримПомощник")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default=ROOT / "data")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.store = Store(args.data)
        print(f"StreamHelper: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
