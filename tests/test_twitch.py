"""Приёмка обработки данных Twitch с воспроизводимыми ответами API."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import publication
import twitch_data as data
from streams import Store
from twitch import Twitch


class TwitchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.twitch = Twitch(self.store)
        self.started = int(time.time()) - 90
        self.live = {"id": "TwitchStream1", "started_at": data.iso(self.started),
                     "title": "Первый рейд", "game_name": "Just Chatting"}

    def remote(self, endpoint, query=None, body=None):
        response = {
            "streams": {"data": [self.live] if self.live else []},
            "chat/chatters": (
                {"data": [{"user_id": "j", "user_name": "Тихий зритель"}], "pagination": {"cursor": "page2"}}
                if "after" not in (query or {}) else
                {"data": [{"user_id": "k", "user_name": "Ещё зритель"}]}
            ),
            "moderation/moderators": {"data": [{"user_name": "Модератор"}]},
            "bits/leaderboard": {"data": [{"user_name": "Сова", "score": 200}]},
            "videos": {"data": [{"id": "vod1", "stream_id": "TwitchStream1"}]},
        }
        if endpoint == "clips":
            if body is not None:
                self.assertEqual(query, {"broadcaster_id": "owner", "duration": 30})
                return {"data": [{"id": "new-clip"}]}
            live_clip = {"id": "new-clip", "video_id": "vod1", "title": "Лучший момент",
                         "url": "https://clips.twitch.tv/NewClip", "created_at": data.iso(self.started + 45)}
            other = {**live_clip, "id": "old-clip", "video_id": "old", "title": "Чужой VOD"}
            return {"data": [live_clip] if "id" in query else [other, live_clip]}
        return response[endpoint]

    def event(self, kind, event_id, payload, elapsed=30):
        self.twitch.notification("owner", {
            "metadata": {"subscription_type": kind, "message_id": event_id,
                         "message_timestamp": data.iso(self.started + elapsed)},
            "payload": {"event": {"broadcaster_user_id": "owner", **payload}},
        })

    def test_collection_and_snapshot(self):
        with patch.object(self.twitch, "helix", side_effect=self.remote):
            self.twitch.sync("owner")
            self.live["game_name"] = "Minecraft"
            self.twitch.sync("owner")
            question = {"chatter_user_name": "Сова", "chatter_user_id": "owl",
                        "message": {"text": "!вопрос Когда рейд?"}}
            self.event("channel.chat.message", "chat1", question)
            self.event("channel.chat.message", "chat1", question)
            self.event("channel.chat.message", "chat2", {**question, "message": {"text": "Привет"}})
            self.event("channel.cheer", "bits1", {"user_id": "owl", "user_name": "Сова", "bits": 150})
            self.event("channel.cheer", "bits1", {"user_id": "owl", "user_name": "Сова", "bits": 150})
            self.twitch.ready = True
            self.twitch.account = {"user_id": "owner"}
            self.assertEqual(self.twitch.create_clip(1), {"id": "new-clip"})
            self.event("stream.offline", "end", {}, elapsed=80)
            self.twitch.sync("owner")  # Helix still advertises this broadcast.
            with self.store.connect(write=True) as db:
                self.assertIsNone(data.active(db, "owner"))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM questions").fetchone()[0], 1)
                card = publication.publish(db, 1, {})
                self.assertEqual(card["duration"], 80)
                self.assertEqual(card["categories"], ["Just Chatting", "Minecraft"])
                self.assertCountEqual(card["audience"], ["Тихий зритель", "Ещё зритель", "Сова"])
                self.assertEqual(card["active_chat"], [{"name": "Сова", "count": 2}])
                self.assertEqual(card["top_bits"], [{"name": "Сова", "count": 150}])
                self.assertEqual(card["bits_today"]["entries"], [{"name": "Сова", "count": 200}])
                self.assertEqual(card["moderators"], ["Модератор"])
                self.assertEqual(card["clips"], [{"title":"Лучший момент", "url":"https://clips.twitch.tv/NewClip"}])
                self.assertNotIn("Когда рейд", str(card))
            self.event("channel.chat.message", "late", question, elapsed=60)
            with Store(self.store.directory).connect() as db:
                self.assertEqual(publication.latest(db), card)
                self.assertEqual(publication.preview(db, 1)["active_chat"][0]["count"], 3)

    def test_poll_recovery_requires_two_successful_offline_responses(self):
        with patch.object(self.twitch, "helix", side_effect=self.remote):
            self.twitch.sync("owner")
            self.live = None
            self.twitch.sync("owner")
            with self.store.connect() as db:
                self.assertIsNotNone(data.active(db, "owner"))
            self.twitch.sync("owner")
            with self.store.connect() as db:
                self.assertIsNone(data.active(db, "owner"))


if __name__ == "__main__":
    unittest.main()
