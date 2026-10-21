import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from conversation_store import ConversationStore, iso
from native_links import conversation_link
from summaries import ClaudeSummaryClient, SummaryService
from time import time


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "summaries.sqlite3"
        self.text = "这是一份需要提炼结论和待办的较长回复。" * 40

    def service(self, generator):
        service = SummaryService(self.path, generator=generator)
        self.addCleanup(service.close)
        return service

    def test_polling_does_not_duplicate_model_calls(self):
        entered, release = Event(), Event()
        calls = []
        def generate(text):
            calls.append(text)
            entered.set()
            release.wait(timeout=2)
            return "实际摘要"
        service = self.service(generate)
        service.describe(self.text, request=True)
        self.assertTrue(entered.wait(timeout=2))
        try:
            for _ in range(10):
                self.assertEqual(service.describe(self.text)["summary_state"], "generating")
        finally:
            release.set()
        service.queue.join()
        self.assertEqual(service.describe(self.text)["summary"], "实际摘要")
        self.assertEqual(calls, [self.text])

    def test_cache_survives_restart_and_new_content_gets_new_summary(self):
        first = self.service(lambda text: "旧回复的摘要")
        first.describe(self.text, request=True)
        first.queue.join()
        first.close()
        calls = []
        second = self.service(lambda text: calls.append(text) or "新回复的摘要")
        self.assertEqual(second.describe(self.text)["summary"], "旧回复的摘要")
        self.assertEqual(calls, [])
        changed = self.text + "补充：仍然需要用户确认。"
        second.describe(changed, request=True)
        second.queue.join()
        self.assertEqual(second.describe(changed)["summary"], "新回复的摘要")
        self.assertEqual(second.describe(self.text)["summary"], "旧回复的摘要")

    def test_live_progress_does_not_trigger_continuous_summarization(self):
        calls = []
        service = self.service(lambda text: calls.append(text) or "摘要")
        result = service.describe(self.text, eligible=False)
        self.assertEqual(result["summary_state"], "waiting")
        self.assertEqual(calls, [])
        self.assertEqual(service.describe("短回复")["summary_state"], "short")
        self.assertEqual(calls, [])

    def test_provider_failure_pauses_calls_until_explicit_retry(self):
        calls = []
        def generate(text):
            calls.append(text)
            if len(calls) == 1:
                raise RuntimeError("额度暂不可用")
            return "恢复后的真实摘要"
        service = self.service(generate)
        service.describe(self.text, request=True)
        service.queue.join()
        self.assertEqual(service.describe(self.text)["summary_state"], "error")
        service.describe(self.text + "different", request=True)
        service.queue.join()
        self.assertEqual(len(calls), 1)
        service.describe(self.text, request=True, retry=True)
        service.queue.join()
        self.assertEqual(service.describe(self.text)["summary"], "恢复后的真实摘要")
        self.assertEqual(len(calls), 2)

    def test_summary_never_replaces_original_transcript(self):
        service = self.service(lambda text: "结论已整理；下一步仍需人工确认。")
        root = Path(self.temp.name)
        folder = root / "codex" / "sessions"
        folder.mkdir(parents=True)
        path = folder / "session.jsonl"
        rows = [
            {"type": "session_meta", "payload": {"id": "example"}},
            {"type": "response_item", "timestamp": iso(time()), "payload": {
                "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": self.text}]}},
            {"type": "event_msg", "timestamp": iso(time()), "payload": {"type": "task_complete"}},
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        original = path.read_bytes()
        store = ConversationStore(root / "codex", root / "claude", summaries=service)
        first_card = store.snapshot()["conversations"][0]
        self.assertEqual(first_card["summary_state"], "idle")
        for _ in range(3):
            store.snapshot()
            store.detail(first_card["id"])
            store.progress(first_card["id"])
        self.assertEqual(service.cache, {})
        self.assertTrue(service.queue.empty())
        with self.assertRaisesRegex(ValueError, "回复已更新"):
            store.request_summary(first_card["id"], "0" * 64)
        store.request_summary(first_card["id"], first_card["summary_key"])
        service.queue.join()
        card = store.snapshot()["conversations"][0]
        self.assertNotEqual(card["preview"], "结论已整理；下一步仍需人工确认。")
        self.assertEqual(card["summary"], "结论已整理；下一步仍需人工确认。")
        self.assertEqual(card["summary_state"], "ready")
        self.assertEqual(store.detail(card["id"])["messages"][-1]["text"], self.text)
        self.assertEqual(path.read_bytes(), original)

    def test_client_sends_complete_text_without_tools_or_new_transcripts(self):
        process = Mock()
        process.returncode = 0
        process.communicate.return_value = (json.dumps({"result": "精炼摘要", "is_error": False}), "")
        with patch("summaries.subprocess.Popen", return_value=process) as launch:
            client = ClaudeSummaryClient(executable="/example/claude")
            self.assertEqual(client(self.text), "精炼摘要")
        command = launch.call_args.args[0]
        self.assertNotIn(self.text, command)
        self.assertTrue(process.communicate.call_args.args[0].endswith(self.text))
        self.assertIn("--no-session-persistence", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--safe-mode", command)

    def test_provider_error_is_not_presented_as_a_summary(self):
        process = Mock()
        process.returncode = 0
        process.communicate.return_value = (json.dumps({"result": "not logged in", "is_error": True}), "")
        with patch("summaries.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "not logged in"):
                ClaudeSummaryClient()(self.text)


class NativeLinkTests(unittest.TestCase):
    def test_both_apps_receive_the_exact_session_id(self):
        identifier = "88fa01dd-3b81-4e8e-94f5-4d104d307a53"
        self.assertEqual(conversation_link("Codex", identifier), "codex://threads/" + identifier)
        self.assertEqual(conversation_link("Claude", identifier), "claude://resume?session=" + identifier)

    def test_untrusted_ids_cannot_become_arbitrary_links(self):
        for value in ["javascript:alert(1)", "../secret", "abc?session=other", None]:
            self.assertIsNone(conversation_link("Codex", value))
            self.assertIsNone(conversation_link("Claude", value))
        self.assertIsNone(conversation_link("Unknown", "88fa01dd-3b81-4e8e-94f5-4d104d307a53"))


if __name__ == "__main__":
    unittest.main()
