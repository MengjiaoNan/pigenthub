"""用模拟日志验证兼容性，避免测试接触真实对话。"""

import json
import tempfile
import unittest
from pathlib import Path

from list_sessions import scan_sessions


class SessionReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "sessions").mkdir()

    def write_session(self, records, tail=""):
        path = self.home / "sessions" / "sample.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in records) + "\n" + tail,
                        encoding="utf-8")
        return path

    @staticmethod
    def message(role, text):
        return {"type": "response_item", "payload": {
            "type": "message", "role": role,
            "content": [{"type": "input_text", "text": text}]}}

    def test_context_internal_messages_and_partial_line(self):
        path = self.write_session([
            {"type": "session_meta", "payload": {"id": "test-1", "cwd": "/demo"}},
            self.message("developer", "internal instructions"),
            self.message("user", "<environment_context>machine details</environment_context>"),
            self.message("user", '<in-app-browser-context source="ambient">page</in-app-browser-context>\n## My request:\n做一个看板'),
            self.message("assistant", "好的"),
            {"type": "event_msg", "payload": {"type": "user_message", "message": "做一个看板"}},
            [], {"payload": []},
        ], tail='{"unfinished":')
        before = path.read_bytes()
        conversations, warnings = scan_sessions(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0].title, "做一个看板")
        self.assertEqual(conversations[0].message_count, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_latest_custom_title_wins(self):
        self.write_session([{"type": "session_meta", "payload": {"id": "test-1"}},
                            self.message("user", "原始请求")])
        (self.home / "session_index.jsonl").write_text(
            json.dumps({"id": "test-1", "thread_name": "旧标题"}) + "\n" +
            json.dumps({"id": "test-1", "thread_name": "我的项目"}) + "\n",
            encoding="utf-8")
        conversations, _ = scan_sessions(self.home)
        self.assertEqual(conversations[0].title, "我的项目")

    def test_missing_directory_has_clear_diagnostic(self):
        conversations, warnings = scan_sessions(self.home / "missing")
        self.assertEqual(conversations, [])
        self.assertIn("Codex conversation directory not found", warnings[0])

    def test_old_event_only_record(self):
        self.write_session([
            {"type": "session_meta", "payload": {"id": "old-1"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "旧会话"}},
        ])
        conversations, _ = scan_sessions(self.home)
        self.assertEqual(conversations[0].title, "旧会话")
        self.assertEqual(conversations[0].message_count, 1)

    def test_unrecognized_file_is_not_a_conversation(self):
        self.write_session([{}, [], {"payload": None}])
        conversations, _ = scan_sessions(self.home)
        self.assertEqual(conversations, [])


if __name__ == "__main__":
    unittest.main()
