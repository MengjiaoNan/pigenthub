import io
import json
from pathlib import Path
import tempfile
from time import time
import unittest
from unittest.mock import patch

from conversation_store import ConversationStore, iso
from install_observers import merge_hooks
from live_events import COMPACTION_WINDOW, LiveEventStore, PENDING_WINDOW, record_hook
from platform_support import hook_references
import observer_hook

SESSION = "88fa01dd-3b81-4e8e-94f5-4d104d307a53"


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "events.sqlite3"
        self.store = LiveEventStore(self.path)
        self.now = time()

    def event(self, name, **fields):
        return {"hook_event_name": name, "session_id": SESSION,
                "tool_name": "Bash", "tool_input": {"command": "echo test", "description": "测试权限请求"}, **fields}

    def state(self, source="Codex"):
        return self.store.snapshot()[source.lower() + ":" + SESSION]

    def card(self):
        return {"status": "running", "status_reason": "运行中", "started_at": iso(self.now - 10), "finished_at": None}

    def test_permission_enters_needs_you_and_matching_result_clears_it(self):
        record_hook(self.path, "Codex", self.event("PermissionRequest"), now=self.now)
        card = self.store.overlay(self.card(), self.state(), now=self.now + 1)
        self.assertEqual(card["status"], "needs_you")
        self.assertEqual(card["pending_requests"][0]["reason"], "测试权限请求")
        record_hook(self.path, "Codex", self.event("PostToolUse"), now=self.now + 2)
        self.assertEqual(self.store.overlay(self.card(), self.state())["status"], "running")

    def test_other_parallel_tool_does_not_clear_pending_approval(self):
        record_hook(self.path, "Codex", self.event("PermissionRequest"))
        record_hook(self.path, "Codex", self.event("PostToolUse", tool_input={"command": "another command"}))
        self.assertEqual(len(self.state()["pending"]), 1)

    def test_stop_or_new_prompt_clears_stale_pending_requests(self):
        for kind in ["Stop", "UserPromptSubmit", "Interrupt", "SessionEnd"]:
            record_hook(self.path, "Codex", self.event("PermissionRequest"))
            record_hook(self.path, "Codex", self.event(kind))
            self.assertEqual(self.state()["pending"], [])

    def test_compaction_stays_running_past_the_normal_idle_window(self):
        record_hook(self.path, "Codex", self.event("PreCompact", turn_id="turn-1"), now=self.now)
        stale = {**self.card(), "status": "unknown", "activity_at": iso(self.now - 100)}
        card = self.store.overlay(dict(stale), self.state(), now=self.now + 180)
        self.assertEqual((card["status"], card["activity_phase"]), ("running", "compacting"))
        self.assertEqual(card["status_reason"], "正在压缩上下文")
        expired = self.store.overlay(dict(stale), self.state(), now=self.now + COMPACTION_WINDOW + 1)
        self.assertEqual(expired["status"], "unknown")

    def test_compaction_clears_on_completion_interrupt_and_new_work(self):
        for event in ["PostCompact", "Stop", "Interrupt", "SessionEnd", "UserPromptSubmit", "PostToolUse"]:
            record_hook(self.path, "Codex", self.event("PreCompact", turn_id="one"), now=self.now)
            record_hook(self.path, "Codex", self.event(event, turn_id="one"), now=self.now + 1)
            self.assertNotIn("compaction", self.state())
        record_hook(self.path, "Codex", self.event("PreCompact", turn_id="new"), now=self.now)
        record_hook(self.path, "Codex", self.event("PostCompact", turn_id="old"), now=self.now + 1)
        self.assertIn("compaction", self.state())

    def test_newer_transcript_activity_or_completion_wins_over_old_compaction_hook(self):
        record_hook(self.path, "Codex", self.event("PreCompact"), now=self.now)
        done = {**self.card(), "status": "done", "finished_at": iso(self.now + 1)}
        self.assertEqual(self.store.overlay(done, self.state(), now=self.now + 2)["status"], "done")
        active = {**self.card(), "activity_at": iso(self.now + 1)}
        self.assertNotIn("activity_phase", self.store.overlay(active, self.state(), now=self.now + 2))

    def test_compaction_hooks_are_passive_and_do_not_change_claude_configuration(self):
        config = merge_hooks({}, "Codex")
        for event in ["PreCompact", "PostCompact"]:
            handler = config["hooks"][event][0]["hooks"][0]
            self.assertTrue(hook_references(handler, "observer_hook.py"))
            self.assertFalse(hook_references(handler, "approval_hook.py"))
        self.assertNotIn("PreCompact", merge_hooks({}, "Claude")["hooks"])

    def test_notifications_do_not_duplicate_permission_request(self):
        record_hook(self.path, "Claude", self.event("PermissionRequest"))
        record_hook(self.path, "Claude", self.event("Notification", notification_type="permission_prompt", message="needs permission"))
        self.assertEqual(len(self.state("Claude")["pending"]), 1)

    def test_question_tool_enters_needs_you_and_tool_answer_clears_it(self):
        event = self.event("PreToolUse", tool_name="AskUserQuestion", tool_use_id="q1", tool_input={"questions": [{"question": "选择哪种方案？"}]})
        record_hook(self.path, "Claude", event)
        self.assertEqual(self.state("Claude")["pending"][0]["kind"], "question")
        record_hook(self.path, "Claude", {**event, "hook_event_name": "PostToolUse"})
        self.assertEqual(self.state("Claude")["pending"], [])

    def test_completed_turn_wins_over_older_permission_and_stale_is_unknown(self):
        record_hook(self.path, "Codex", self.event("PermissionRequest"), now=self.now)
        card = {**self.card(), "status": "done", "finished_at": iso(self.now + 2)}
        self.assertEqual(self.store.overlay(card, self.state(), now=self.now + 3)["status"], "done")
        self.assertEqual(self.store.overlay(self.card(), self.state(), now=self.now + PENDING_WINDOW + 1)["status"], "unknown")

    def test_codex_runtime_session_resolves_to_transcript_thread_id(self):
        event = self.event("PermissionRequest", session_id="a-runtime-session", transcript_path="/logs/rollout-date-" + SESSION + ".jsonl")
        record_hook(self.path, "Codex", event)
        self.assertEqual(len(self.state()["pending"]), 1)

    def test_store_moves_real_transcript_card_without_changing_source_file(self):
        folder = self.root / "codex" / "sessions"
        folder.mkdir(parents=True)
        path = folder / "session.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": SESSION}}) + "\n" +
                        json.dumps({"timestamp": iso(self.now - 5), "type": "event_msg", "payload": {"type": "task_started"}}) + "\n")
        before = path.read_bytes()
        record_hook(self.path, "Codex", self.event("PermissionRequest"), now=self.now)
        store = ConversationStore(self.root / "codex", self.root / "claude", live_events=self.store)
        self.assertEqual(store.snapshot()["conversations"][0]["status"], "needs_you")
        progress = store.progress("codex:" + SESSION)
        self.assertEqual(progress["status"], "needs_you")
        self.assertTrue(any("审批" in event["message"] for event in progress["events"]))
        self.assertEqual(path.read_bytes(), before)

    def test_merging_preserves_permissions_and_other_hooks_and_is_idempotent(self):
        original = {"permissions": {"allow": ["Read"]}, "hooks": {"PermissionRequest": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "existing observer"}]}]}}
        merged = merge_hooks(original, "Codex")
        self.assertEqual(merged["permissions"], original["permissions"])
        self.assertEqual(merged["hooks"]["PermissionRequest"][0], original["hooks"]["PermissionRequest"][0])
        self.assertEqual(merge_hooks(merged, "Codex"), merged)

    def test_hook_outputs_no_approval_decision_even_if_recording_fails(self):
        for side_effect in [None, OSError("disk unavailable")]:
            output = io.StringIO()
            with patch("observer_hook.sys.stdin", io.StringIO(json.dumps(self.event("PermissionRequest")))), \
                 patch("observer_hook.sys.stdout", output), patch("observer_hook.sys.argv", ["observer_hook.py", "codex"]), \
                 patch("observer_hook.record_hook", side_effect=side_effect):
                observer_hook.main()
            self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
