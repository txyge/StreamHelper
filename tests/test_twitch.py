import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, Mock

from donations import Donations
from streamerbot import StreamerBot
from streams import Store, mark
from summary import detail

def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.donations = Donations(self.store, 18767)
        self.finished = Mock()
        self.bot = StreamerBot(self.store, self.finished)

    def send(self, kind, when, **data):
        self.bot.event({"event":{"source":"Twitch","type":kind}, "timeStamp":iso(when),"data":data})

    def test_summary(self):
        self.send("ChatMessage", 95, text="!вопрос Рано", user={"id":"pre","name":"Рано"})
        self.send("StreamOnline", 101, id="stream", startedAt=iso(100), game={"Name":"Minecraft"})
        self.send("StreamOnline", 102, id="stream", startedAt=iso(100))
        self.send("StreamUpdate", 103, status="Обсуждаем игру", game={"name":"Just Chatting"})
        for _ in range(2):
            self.send("ChatMessage", 104, messageId="q", text="!вопрос Где база?",
                      user={"id":"mod","name":"Мод","badges":[{"name":"moderator"}]})
        self.send("UserTimedOut", 105, moderator={"id":"other","name":"Второй"})
        self.bot.viewers([{"id":"viewer","type":"twitch","display":"Зритель","previousActive":iso(105)}])
        with self.store.connect(write=True) as db, patch("streams.time.time", return_value=106):
            self.assertEqual(mark(db, 1, {"label":"Момент"})["seconds"], 6)
        self.send("StreamOffline", 110)
        self.finished.assert_called_once_with(1)
        self.send("ChatMessage", 111, text="!вопрос Поздно", user={"id":"late","name":"Поздно"})
        self.donations.tokens = {"access_token":"fake"}
        def item(key, when):
            return {"id":key,"created_at":iso(when),"username":key,"amount":42,"currency":"RUB"}
        pages = [{"data":[item("После",111),item("Первый",110)],"links":{"next":"page=2"}},
                 {"data":[item("Первый",110),item("Второй",105),item("До",99)],"links":{"next":None}}]
        with patch("donations.fetch", side_effect=pages):
            self.donations.sync(1)
        with self.store.connect() as db:
            report = detail(db, 1)
            self.assertEqual(report["duration"], 10)
            self.assertEqual([row["category"] for row in report["topics"]],["Minecraft","Just Chatting"])
            self.assertEqual(report["title"], "Обсуждаем игру")
            self.assertCountEqual(report["viewers"], ["Зритель","Мод","Второй"])
            self.assertCountEqual(report["moderators"], ["Мод","Второй"])
            self.assertEqual([row["name"] for row in report["donations"]], ["Второй","Первый"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM questions").fetchone()[0],1)

    def test_subscription_and_oauth(self):
        connection = Mock()
        connection.recv.side_effect = ['{"request":"Hello"}','{"id":"streams","status":"ok"}']
        self.bot.subscribe(connection)
        request = json.loads(connection.send.call_args.args[0])
        self.assertIn("ChatMessage", request["events"]["Twitch"])
        self.assertIn("StreamUpdate", request["events"]["Twitch"])
        self.assertEqual(self.donations.configure({"client_id":"123","client_secret":"test"}),
                         {"configured":True})
        self.donations = Donations(self.store, 18767)
        self.assertTrue(self.donations.status()["configured"])
        self.assertNotIn("test", str(self.donations.status()))
        from urllib.parse import urlsplit, parse_qs
        query = parse_qs(urlsplit(self.donations.authorization()).query)
        self.assertEqual(query["scope"], ["oauth-donation-index oauth-user-show"])
        query["code"] = ["sample"]
        with patch("donations.fetch", side_effect=[{"access_token":"fake"}, {"data":{"name":"Стример","email":"private@example.com"}}]):
            self.donations.callback(query)
        self.assertTrue(self.donations.status()["connected"])
        saved = Donations(self.store, 18767).status()
        self.assertTrue(saved["connected"])
        self.assertEqual(saved["account"], "Стример")
        self.assertNotIn("private@example.com", str(saved))
        self.donations.configure({"client_id":"456","client_secret":"different"})
        self.assertFalse(Donations(self.store, 18767).status()["connected"])
