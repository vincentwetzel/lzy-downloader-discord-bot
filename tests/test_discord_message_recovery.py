import asyncio
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import lzy_downloader_discord_bridge as bridge


class FakeMessage:
    def __init__(self, message_id, content, author_id=99, channel_id=456):
        self.id = message_id
        self.content = content
        self.author = SimpleNamespace(id=author_id)
        self.channel = SimpleNamespace(id=channel_id)


class FakeChannel:
    id = 456

    def __init__(self, messages):
        self.messages = messages

    def history(self, limit):
        async def generate():
            for message in self.messages:
                yield message

        return generate()

    async def fetch_message(self, message_id):
        raise AssertionError("the migration test should use bounded history")


class DiscordMessageRecoveryTests(unittest.TestCase):
    @staticmethod
    def temporary_state_path():
        """Returns a unique repository-local state path for restricted runners."""
        return Path(__file__).parents[1] / (
            f".test-discord-message-state-{uuid.uuid4().hex}.json"
        )

    def test_message_state_round_trip(self):
        message = FakeMessage(123, "⏳ **Downloading:** **Example title**")
        state_path = self.temporary_state_path()
        try:
            with patch.object(
                bridge, "get_discord_message_state_path", return_value=str(state_path)
            ):
                bridge.remember_discord_messages(
                    "job-1", "https://example.test/video", "video", [message]
                )
                state = bridge.load_discord_message_state()

                self.assertEqual(
                    state["job-1"]["messages"][0]["message_id"], 123
                )
                bridge.forget_discord_messages("job-1")
                self.assertEqual(bridge.load_discord_message_state(), {})
        finally:
            state_path.unlink(missing_ok=True)
            Path(str(state_path) + ".tmp").unlink(missing_ok=True)

    def test_legacy_history_migration_finds_all_duplicate_status_messages(self):
        messages = [
            FakeMessage(1, "🟢 **LzyDownloader Discord Bridge is now online!**"),
            FakeMessage(2, "⏳ **Downloading:** **Example title**"),
            FakeMessage(3, "⏳ **Downloading:** **Example title**"),
        ]
        item = {
            "id": "job-1",
            "url": "https://example.test/video",
            "options": {"initial_title": "Example title"},
        }
        bot = bridge.LzyBot()
        bot._connection.user = SimpleNamespace(id=99)

        state_path = self.temporary_state_path()
        try:
            with patch.object(
                bridge, "get_discord_message_state_path", return_value=str(state_path)
            ):
                found = asyncio.run(
                    bot.find_recovery_messages(FakeChannel(messages), [item])
                )
        finally:
            state_path.unlink(missing_ok=True)
            Path(str(state_path) + ".tmp").unlink(missing_ok=True)

        self.assertEqual([message.id for message in found[0]], [2, 3])


if __name__ == "__main__":
    unittest.main()
