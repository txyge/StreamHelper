"""Локальный HTTP-сервер проекта."""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chat
import streams
from streams import Problem, ROOT, Store

STATIC = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
ACTIONS = {
    "finish": streams.finish, "marks": streams.mark,
    "message": chat.message, "restore": chat.restore,
    "answer": chat.answer, "rules": chat.settings,
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
            self.dispatch(method, self.path.split("?", 1)[0])
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
            if method == "GET" and action is None:
                with store.connect() as db:
                    result = {**streams.detail(db, sid), **chat.detail(db, sid)}
                self.send_json(result)
                return
            if method == "POST" and action in ACTIONS:
                data = self.json_body()
                with store.connect(write=True) as db:
                    result = ACTIONS[action](db, sid, data)
                self.send_json(result)
                return
        raise Problem("Страница не найдена.", 404)


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
