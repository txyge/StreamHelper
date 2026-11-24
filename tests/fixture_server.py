"""Локальный сервер теста с заранее доставленными событиями Twitch."""
import argparse
import time
from http.server import ThreadingHTTPServer

import twitch_data as data
from app import Handler
from streams import Store
from twitch import Twitch

parser = argparse.ArgumentParser()
parser.add_argument("directory")
args = parser.parse_args()
with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
    server.store = Store(args.directory)
    server.twitch = Twitch(server.store)
    started = time.time() - 150
    with server.store.connect(write=True) as db:
        data.sync_stream(db, "owner", {"id":"fake1", "title":"Тестовый эфир Twitch",
                                       "game_name":"Just Chatting", "started_at":data.iso(started)})
        for index in range(2):
            data.receive(db, "owner", "channel.chat.message", f"msg{index}", started + 30 + index, {
                "broadcaster_user_id":"owner", "chatter_user_name":"Сова", "chatter_user_id":"owl",
                "message":{"text":"!вопрос Как дела?" if index else "Привет"}
            })
        data.receive(db, "owner", "channel.cheer", "bits1", started + 42, {
            "broadcaster_user_id":"owner", "user_name":"Сова", "user_id":"owl", "bits":42
        })
        data.save_clip(db, 1, {"id":"clip", "title":"Победа", "url":"https://clips.twitch.tv/TestClip",
                               "created_at":data.iso(started+75)})
        data.sync_stream(db, "owner", None, started + 120)
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
