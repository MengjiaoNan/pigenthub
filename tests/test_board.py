"""Behavior tests use only synthetic logs in temporary directories."""
import json
import tempfile
import unittest
from pathlib import Path
from time import time

from conversation_store import ConversationStore, iso, read_claude, read_codex


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.codex = self.root / "codex"
        self.claude = self.root / "claude"
        (self.codex / "sessions").mkdir(parents=True)
        (self.claude / "projects" / "sample").mkdir(parents=True)
        self.now = time()
        self.path = self.codex / "sessions" / "sample.jsonl"

    def write(self, path, rows, tail=""):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="utf-8")
        return path

    def event(self, kind, offset=0, **fields):
        return {"type": "event_msg", "timestamp": iso(self.now + offset),
                "payload": {"type": kind, **fields}}

    def meta(self, **fields):
        return {"type": "session_meta", "timestamp": iso(self.now - 60),
                "payload": {"id": "test", "cwd": "/project", **fields}}

    def message(self, role, text, offset=0):
        return {"type": "response_item", "timestamp": iso(self.now + offset),
                "payload": {"type": "message", "role": role,
                            "content": [{"type": "input_text", "text": text}]}}

    def test_quiet_codex_turn_stays_running_until_explicit_end(self):
        self.write(self.path, [self.meta(), self.event("task_started", -200, turn_id="one"),
                               self.message("assistant", "still working", -180)])
        transcript = read_codex(self.path)
        self.assertEqual(transcript.card(self.now)["status"], "running")
        self.assertIn("等待", transcript.card(self.now)["status_reason"])
        self.assertNotEqual(transcript.card(self.now)["status"], "done")
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self.event("task_complete", turn_id="one")) + "\n")
        self.assertEqual(read_codex(self.path).card(self.now)["status"], "done")

    def test_full_history_is_opt_in_cached_and_invalidated_without_summary_calls(self):
        rows = [self.meta()] + [self.message("user" if i % 2 == 0 else "assistant", f"message {i}", i)
                                for i in range(230)]
        self.write(self.path, rows)
        before = self.path.read_bytes()
        store = ConversationStore(self.codex, self.claude)
        recent = store.detail("codex:test")
        self.assertEqual(len(recent["messages"]), 200)
        self.assertEqual(recent["messages_omitted"], 30)
        full = store.detail("codex:test", full=True)
        self.assertEqual(len(full["messages"]), 230)
        self.assertEqual(full["messages"][0]["text"], "message 0")
        self.assertEqual(full["messages_omitted"], 0)
        from unittest.mock import patch
        with patch("conversation_store.read_codex", side_effect=AssertionError("should reuse full cache")):
            self.assertEqual(len(store.detail("codex:test", full=True)["messages"]), 230)
        self.assertEqual(self.path.read_bytes(), before)
        rows.append(self.message("user", "new question", 231))
        self.write(self.path, rows)
        store.last_scan = 0
        self.assertEqual(store.detail("codex:test", full=True)["messages"][-1]["text"], "new question")

    def test_claude_full_reader_and_missing_project(self):
        path = self.claude / "projects" / "sample" / "chat.jsonl"
        rows = [{"type": "user" if i % 2 == 0 else "assistant", "sessionId": "loose",
                 "timestamp": iso(self.now + i),
                 "message": {"content": [{"type": "text", "text": f"text {i}"}]}}
                for i in range(220)]
        self.write(path, rows)
        store = ConversationStore(self.codex, self.claude)
        self.assertEqual(store.snapshot()["conversations"][0]["project"], "")
        self.assertEqual(len(store.detail("claude:loose", full=True)["messages"]), 220)

    def test_compaction_completion_refreshes_activity_without_exposing_its_summary(self):
        rows = [self.meta(), self.event("task_started", -150)]
        rows.append({"type": "compacted", "timestamp": iso(self.now - 1),
                     "payload": {"message": "INTERNAL COMPACTION SUMMARY", "replacement_history": []}})
        self.write(self.path, rows)
        item = read_codex(self.path)
        self.assertEqual(item.card(self.now)["status"], "running")
        self.assertEqual(item.card(self.now)["status_reason"], "上下文压缩已完成，继续处理本轮")
        self.assertFalse(any("INTERNAL" in m["text"] for m in item.messages))
        self.assertEqual(item.events[-1]["message"], "上下文压缩已完成")
        self.assertEqual(item.card(self.now + 200)["status"], "running")

    def test_codex_tool_output_refreshes_activity_without_exposing_payload(self):
        self.write(self.path, [self.meta(), self.event("task_started", -300, turn_id="one"),
                              {"type": "response_item", "timestamp": iso(self.now - 200),
                               "payload": {"type": "custom_tool_call", "name": "long_tool"}},
                              {"type": "response_item", "timestamp": iso(self.now - 1),
                               "payload": {"type": "custom_tool_call_output", "output": "PRIVATE TOOL DATA"}}])
        item = read_codex(self.path)
        self.assertEqual(item.card(self.now)["activity_at"], iso(self.now - 1))
        self.assertEqual(item.card(self.now)["status"], "running")
        self.assertEqual(item.events[-1]["message"], "工具执行结果已写入")
        self.assertFalse(any("PRIVATE" in message["text"] for message in item.messages))

    def test_compaction_completion_does_not_reopen_a_finished_turn(self):
        self.write(self.path, [self.meta(), self.event("task_complete", -10),
                               {"type": "compacted", "timestamp": iso(self.now), "payload": {}}])
        self.assertEqual(read_codex(self.path).card(self.now)["status"], "done")

    def test_inline_progress_is_bounded_to_this_turn_and_preserves_full_detail(self):
        full_reply = "Latest progress with all the details. " * 60
        rows = [self.meta(), self.event("task_started", -30, turn_id="old"),
                self.message("assistant", "OLD TURN CONTENT", -25),
                self.event("task_complete", -20, turn_id="old"),
                self.event("task_started", -10, turn_id="new"), self.message("user", "New task", -9)]
        for index in range(10):
            rows.append({"type": "response_item", "timestamp": iso(self.now - 8 + index / 2),
                         "payload": {"type": "function_call", "name": "tool_" + str(index)}})
        rows.append(self.message("assistant", full_reply, -1))
        self.write(self.path, rows)
        before = self.path.read_bytes()
        store = ConversationStore(self.codex, self.claude)
        progress = store.progress("codex:test")
        self.assertEqual(progress["status"], "running")
        self.assertEqual(len(progress["events"]), 6)
        self.assertTrue(all("tool_" in event["message"] for event in progress["events"]))
        self.assertNotIn("messages", progress)
        self.assertTrue(progress["latest_update"]["text"].startswith("Latest progress"))
        self.assertLessEqual(len(progress["latest_update"]["text"]), 701)
        self.assertEqual(store.detail("codex:test")["messages"][-1]["text"], full_reply)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(store.progress("missing:session"))

    def test_new_turn_progress_does_not_show_an_old_reply(self):
        self.write(self.path, [self.meta(), self.message("assistant", "Old answer", -10),
                               self.event("task_complete", -9), self.event("task_started", -2),
                               self.message("user", "New question", -1)])
        progress = ConversationStore(self.codex, self.claude).progress("codex:test")
        self.assertIsNone(progress["latest_update"])
        self.assertEqual(len(progress["events"]), 1)

    def test_new_turn_moves_completed_conversation_back_to_running(self):
        self.write(self.path, [self.meta(), self.event("task_started", -10, turn_id="one"),
                               self.event("task_complete", -9, turn_id="one"),
                               self.event("task_started", -1, turn_id="two"),
                               self.message("user", "new question")])
        self.assertEqual(read_codex(self.path).card(self.now)["status"], "running")

    def test_new_message_without_start_does_not_keep_old_done_state(self):
        self.write(self.path, [self.meta(), self.event("task_complete", -1),
                               self.message("assistant", "old answer", -1),
                               self.message("user", "new question")])
        card = read_codex(self.path).card(self.now)
        self.assertEqual(card["status"], "unknown")
        self.assertEqual(card["preview"], "new question")
        self.assertEqual(card["preview_kind"], "任务摘录")

    def test_old_turn_completion_does_not_finish_new_turn(self):
        self.write(self.path, [self.meta(), self.event("task_started", -1, turn_id="two"),
                               self.event("task_complete", turn_id="one")])
        self.assertEqual(read_codex(self.path).card(self.now)["status"], "running")

    def test_partial_line_does_not_hide_complete_reply(self):
        reply = "完整回复\n" + "较长的正文" * 100
        self.write(self.path, [self.meta(), self.message("user", "question", -2),
                               self.message("assistant", reply, -1), self.event("task_complete")],
                   tail='{"unfinished":')
        before = self.path.read_bytes()
        transcript = read_codex(self.path)
        self.assertEqual(transcript.messages[-1]["text"], reply)
        self.assertLess(len(transcript.card(self.now)["preview"]), len(reply))
        self.assertEqual(self.path.read_bytes(), before)

    def test_event_only_logs_keep_terminal_state_and_title(self):
        self.write(self.path, [self.meta(), self.event("task_started", -3),
                               self.event("user_message", -2, message="我的任务"),
                               self.event("task_complete", last_agent_message="完成了")])
        transcript = read_codex(self.path)
        self.assertEqual(transcript.card(self.now)["status"], "done")
        self.assertEqual(transcript.title, "我的任务")
        self.assertEqual([m["role"] for m in transcript.messages], ["user", "assistant"])

    def test_subagents_are_excluded(self):
        self.write(self.path, [self.meta(source={"subagent": {"other": "guardian"}})])
        self.assertIsNone(read_codex(self.path))

    def test_cache_picks_up_appended_records_and_title_index_changes(self):
        self.write(self.path, [self.meta(), self.message("user", "Original"), self.event("task_started")])
        store = ConversationStore(self.codex, self.claude)
        self.assertEqual(store.snapshot()["conversations"][0]["status"], "running")
        with self.path.open("a") as stream:
            stream.write(json.dumps(self.event("task_complete", last_agent_message="Updated")) + "\n")
        (self.codex / "session_index.jsonl").write_text(json.dumps({"id": "test", "thread_name": "Renamed"}) + "\n")
        with store.lock:
            store.scan(force=True)
        card = store.snapshot()["conversations"][0]
        self.assertEqual((card["status"], card["title"], card["preview"]), ("done", "Renamed", "Updated"))
        self.assertNotIn("messages", card)
        self.assertIsNone(store.detail("../../outside"))

    def claude_row(self, role, content, offset=0, **fields):
        return {"type": role, "sessionId": "claude-test", "cwd": "/project", "timestamp": iso(self.now + offset),
                "message": {"role": role, "content": content, **fields}}

    def test_claude_tool_use_is_not_a_completed_reply(self):
        path = self.claude / "projects" / "sample" / "session.jsonl"
        self.write(path, [self.claude_row("user", "fix this", -5),
                          self.claude_row("assistant", [{"type": "tool_use", "name": "Read"}], stop_reason="tool_use")])
        transcript = read_claude(path)
        self.assertEqual(transcript.card(self.now)["status"], "running")
        self.assertEqual(transcript.card(self.now + 200)["status"], "unknown")

    def test_claude_end_turn_and_future_question(self):
        path = self.claude / "projects" / "sample" / "session.jsonl"
        rows = [self.claude_row("user", "question", -5),
                self.claude_row("assistant", [{"type": "text", "text": "answer"}], -1, stop_reason="end_turn")]
        self.write(path, rows)
        self.assertEqual(read_claude(path).card(self.now)["status"], "done")
        self.write(path, rows + [self.claude_row("user", "next question")])
        self.assertEqual(read_claude(path).card(self.now)["status"], "unknown")

    def test_claude_hidden_context_and_sidechains_do_not_become_cards(self):
        path = self.claude / "projects" / "sample" / "session.jsonl"
        self.write(path, [{**self.claude_row("user", "internal"), "isMeta": True},
                          {**self.claude_row("assistant", "internal reply"), "isSidechain": True}])
        self.assertIsNone(read_claude(path))

    def test_source_ids_do_not_collide_and_removing_log_removes_card(self):
        self.write(self.path, [self.meta(id="same"), self.message("user", "Codex question")])
        other = self.claude / "projects" / "sample" / "session.jsonl"
        self.write(other, [{**self.claude_row("user", "Claude question"), "sessionId": "same"}])
        store = ConversationStore(self.codex, self.claude)
        self.assertEqual({c["id"] for c in store.snapshot()["conversations"]}, {"codex:same", "claude:same"})
        self.path.unlink()
        with store.lock:
            store.scan(force=True)
        self.assertEqual(len(store.snapshot()["conversations"]), 1)


if __name__ == "__main__":
    unittest.main()
