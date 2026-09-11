import asyncio
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


class FakeWebhookRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


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

    def test_api_port_discovery_uses_valid_port_and_default_fallback(self):
        data_path = Path(__file__).parents[1] / f".test-api-port-{uuid.uuid4().hex}"
        data_path.mkdir()
        data_dir = str(data_path)
        try:
            with patch.object(bridge, "get_lzy_data_dir", return_value=data_dir):
                Path(data_dir, "api_port.txt").write_text("18765\n", encoding="ascii")
                self.assertEqual(bridge.get_lzy_api_port(), 18765)
                self.assertEqual(bridge.get_lzy_api_base_url(), "http://127.0.0.1:18765")

                Path(data_dir, "api_port.txt").write_text("70000\n", encoding="ascii")
                self.assertEqual(bridge.get_lzy_api_port(), bridge.DEFAULT_API_PORT)
        finally:
            shutil.rmtree(data_path, ignore_errors=True)

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

    def test_queue_backup_uses_shared_coordinator_directory(self):
        with patch.object(bridge, "get_lzy_data_dir", return_value="/shared/LzyDownloader"):
            self.assertEqual(
                bridge.get_download_backup_path(),
                os.path.join("/shared/LzyDownloader", "downloads_backup.json"),
            )
            self.assertEqual(
                bridge.get_discord_message_state_path(),
                os.path.join(
                    "/shared/LzyDownloader", "Server", "discord_message_state.json"
                ),
            )

    def test_queue_backup_reads_legacy_file_until_coordinator_migrates_it(self):
        shared_dir = "/shared/LzyDownloader"
        legacy_path = os.path.join(shared_dir, "Server", "downloads_backup.json")
        with patch.object(bridge, "get_lzy_data_dir", return_value=shared_dir), \
             patch.object(bridge.os.path, "exists", side_effect=lambda path: path == legacy_path):
            self.assertEqual(bridge.get_download_backup_path(), legacy_path)

    def test_cleanup_does_not_terminate_shared_coordinator(self):
        process = Mock()
        process.poll.return_value = None
        previous_process = bridge._lzy_process
        try:
            bridge._lzy_process = process
            bridge.cleanup_subprocess()
            process.terminate.assert_not_called()
            self.assertIsNone(bridge._lzy_process)
        finally:
            bridge._lzy_process = previous_process

    def test_terminal_enqueue_rejection_closes_tracked_job(self):
        bot = bridge.LzyBot()
        job_id = "pending-request-job"
        url = "https://example.test/video"
        bot.active_jobs[job_id] = bridge.build_active_job_data(url)

        response = asyncio.run(
            bot.handle_webhook(
                FakeWebhookRequest(
                    {
                        "job_id": job_id,
                        "url": url,
                        "status": "failed",
                        "error": "Another download request is already being processed.",
                    }
                )
            )
        )

        self.assertEqual(response.status, 200)
        self.assertTrue(bot.active_jobs[job_id]["is_final"])
        self.assertEqual(bot.active_jobs[job_id]["final_status"], "failed")
        self.assertEqual(
            bot.active_jobs[job_id]["error"],
            "Another download request is already being processed.",
        )

    def test_stream_complete_does_not_close_job_before_finalization(self):
        bot = bridge.LzyBot()
        job_id = "post-processing-job"
        url = "https://example.test/video"
        bot.active_jobs[job_id] = bridge.build_active_job_data(url)

        for status in ("Complete", "Applying metadata..."):
            response = asyncio.run(
                bot.handle_webhook(
                    FakeWebhookRequest(
                        {"job_id": job_id, "url": url, "status": status}
                    )
                )
            )
            self.assertEqual(response.status, 200)
            self.assertFalse(bot.active_jobs[job_id]["is_final"])

        response = asyncio.run(
            bot.handle_webhook(
                FakeWebhookRequest(
                    {
                        "job_id": job_id,
                        "url": url,
                        "status": "Completed",
                        "progress": 100,
                    }
                )
            )
        )

        self.assertEqual(response.status, 200)
        self.assertTrue(bot.active_jobs[job_id]["is_final"])
        self.assertEqual(bot.active_jobs[job_id]["final_status"], "completed")

    def test_secondary_server_exit_waits_for_existing_api(self):
        process = Mock()
        process.poll.return_value = 0
        response = Mock(status_code=200)
        previous_process = bridge._lzy_process
        try:
            with patch.object(bridge, "get_lzy_api_key", side_effect=[None, "shared-token"]), \
                 patch.object(bridge, "load_dotenv"), \
                 patch.object(bridge.os.path, "exists", return_value=True), \
                 patch.object(bridge, "validate_windows_executable_loadable"), \
                 patch.object(bridge.subprocess, "Popen", return_value=process), \
                 patch.object(bridge.requests, "get", return_value=response), \
                 patch.object(bridge.time, "sleep"):
                bridge.check_api_health()
            process.terminate.assert_not_called()
        finally:
            bridge._lzy_process = previous_process


if __name__ == "__main__":
    unittest.main()
