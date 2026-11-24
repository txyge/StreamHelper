import sys
import time
from http.server import ThreadingHTTPServer

from app import Handler
import donations
from donations import Donations
from streamerbot import StreamerBot
from streams import Store
from tests.test_twitch import iso

def fake_donation_api(path, token=None, form=None):
    if path == "/oauth/token":
        return {"access_token":"fixture"}
    if path == "/api/v1/user/oauth":
        return {"data":{"name":"Тестовый стример"}}
    raise AssertionError(path)


donations.fetch = fake_donation_api

with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
    server.store = Store(sys.argv[1])
    server.donations = Donations(server.store, server.server_port)
    server.bot = StreamerBot(server.store, server.donations.sync_later)
    started = int(time.time()) - 120
    def send(kind, **data):
        server.bot.event({"event":{"source":"Twitch","type":kind},
                          "timeStamp":iso(started + 10),"data":data})
    send("StreamOnline", id="stream", startedAt=iso(started), game={"Name":"Minecraft"})
    send("StreamUpdate", status="Строим базу", game={"name":"Minecraft"})
    send("ChatMessage", messageId="q", text="!вопрос Где база?",
         user={"id":"mod","name":"Модератор","badges":[{"name":"moderator"}]})
    with server.store.connect(write=True) as db:
        db.execute("INSERT INTO session_donations VALUES (1,'1',?,'Донатер','200','RUB')", (started+15,))
        db.execute("INSERT INTO donation_sync VALUES (1,?)", (started+15,))
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
