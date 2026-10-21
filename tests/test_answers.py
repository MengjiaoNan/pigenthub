"""Answering agent requests from the board, sending messages, focus and settings."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from time import time
from unittest.mock import patch

import approval_hook
from agent_runner import AgentRunner, resume_command
from board_settings import board_online, load_focus, load_settings, mark_offline, mark_online, save_focus, save_settings
from live_events import LiveEventStore, record_hook, submit_decision, take_decision, wait_for_decision

SESSION = "88fa01dd-3b81-4e8e-94f5-4d104d307a53"
KEY = "claude:" + SESSION


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "live.sqlite3"
        self.now = time()

    def event(self, kind="PermissionRequest", **fields):
        return {"session_id": SESSION, "hook_event_name": kind, "tool_name": "Bash",
                "tool_input": {"command": "rm -rf build"}, **fields}

    def pending(self):
        return LiveEventStore(self.db).snapshot()[KEY]["pending"]

    def ask(self, wait=60, **fields):
        record_hook(self.db, "Claude", self.event(**fields), now=self.now, request_id="req-0001", answer_until=self.now + wait)

    def test_board_answer_reaches_the_waiting_hook_and_clears_the_request(self):
        self.ask()
        card = LiveEventStore.overlay({"status": "running"}, LiveEventStore(self.db).snapshot()[KEY], now=self.now + 1)
        self.assertEqual(card["status"], "needs_you")
        self.assertTrue(card["pending_requests"][0]["answerable"])
        self.assertEqual(card["pending_requests"][0]["actions"], ["allow", "deny", "reply", "stop"])
        self.assertIsNone(submit_decision(self.db, KEY, "req-0001", "reply", "use make clean instead", now=self.now + 2))
        self.assertEqual(self.pending()[0]["answered"], "reply")
        decision = wait_for_decision(self.db, KEY, "req-0001", self.now + 60, clock=lambda: self.now + 3, pause=lambda _: None)
        self.assertEqual(decision, {"action": "reply", "message": "use make clean instead"})
        self.assertEqual(self.pending(), [])
        events = LiveEventStore(self.db).snapshot()[KEY]["events"]
        self.assertIn("use make clean instead", events[-1]["message"])

    def test_late_answer_after_hand_back_is_refused(self):
        self.ask(wait=5)
        self.assertIsNone(take_decision(self.db, KEY, "req-0001", give_up=True, now=self.now + 6))
        self.assertTrue(self.pending()[0]["handed_back"])
        self.assertEqual(submit_decision(self.db, KEY, "req-0001", "allow", now=self.now + 7), "Time's up for answering here. Please answer in the agent app.")
        card = LiveEventStore.overlay({"status": "running"}, LiveEventStore(self.db).snapshot()[KEY], now=self.now + 8)
        self.assertFalse(card["pending_requests"][0]["answerable"])

    def test_answers_are_validated(self):
        self.ask()
        self.assertEqual(submit_decision(self.db, KEY, "req-0001", "reply", "  ", now=self.now), "Write a reply first.")
        self.assertEqual(submit_decision(self.db, KEY, "unknown-id", "allow", now=self.now), "This request has already ended.")
        self.assertIsNone(submit_decision(self.db, KEY, "req-0001", "allow", now=self.now))
        self.assertEqual(submit_decision(self.db, KEY, "req-0001", "deny", now=self.now), "This request was already answered.")

    def test_questions_accept_only_reply_or_stop(self):
        record_hook(self.db, "Claude", self.event("PreToolUse", tool_name="AskUserQuestion",
                                                  tool_input={"questions": [{"question": "Which port?"}]}),
                    now=self.now, request_id="req-0002", answer_until=self.now + 60)
        self.assertEqual(submit_decision(self.db, KEY, "req-0002", "allow", now=self.now), "That action isn't available for this request.")
        self.assertIsNone(submit_decision(self.db, KEY, "req-0002", "reply", "8080", now=self.now))

    def test_hook_output_formats(self):
        allow = approval_hook.hook_output("Claude", "PermissionRequest", {"action": "allow"})
        self.assertEqual(allow["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        stop = approval_hook.hook_output("Claude", "PermissionRequest", {"action": "stop"})
        self.assertTrue(stop["hookSpecificOutput"]["decision"]["interrupt"])
        codex_stop = approval_hook.hook_output("Codex", "PermissionRequest", {"action": "stop"})
        self.assertNotIn("interrupt", codex_stop["hookSpecificOutput"]["decision"])
        reply = approval_hook.hook_output("Codex", "PermissionRequest", {"action": "reply", "message": "try again"})
        self.assertIn("try again", reply["hookSpecificOutput"]["decision"]["message"])
        answer = approval_hook.hook_output("Claude", "PreToolUse", {"action": "reply", "message": "8080"})
        self.assertEqual(answer["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("8080", answer["hookSpecificOutput"]["permissionDecisionReason"])

    def run_hook(self, online, prefix=""):
        output = io.StringIO()
        payload = prefix + json.dumps(self.event())
        with patch.object(approval_hook, "ROOT", self.root), patch("approval_hook.board_online", return_value=online), \
             patch("approval_hook.wait_for_decision", return_value={"action": "allow", "message": ""}) as waited, \
             patch("approval_hook.sys.stdin", io.StringIO(payload)), patch("approval_hook.sys.stdout", output), \
             patch("approval_hook.sys.argv", ["approval_hook.py", "claude"]):
            approval_hook.main()
        return output.getvalue(), waited

    def test_hook_waits_only_while_the_board_is_running(self):
        output, waited = self.run_hook(online=False)
        self.assertEqual(output, "")
        waited.assert_not_called()
        output, waited = self.run_hook(online=True)
        self.assertEqual(json.loads(output)["hookSpecificOutput"]["decision"]["behavior"], "allow")

    def test_hook_failure_never_decides(self):
        output = io.StringIO()
        with patch("approval_hook.sys.stdin", io.StringIO("not json")), patch("approval_hook.sys.stdout", output), \
             patch("approval_hook.sys.argv", ["approval_hook.py", "claude"]):
            approval_hook.main()
        self.assertEqual(output.getvalue(), "")

    def test_hook_accepts_utf8_bom_from_windows_forwarding(self):
        output, waited = self.run_hook(online=True, prefix="\ufeff")
        waited.assert_called_once()
        self.assertEqual(json.loads(output)["hookSpecificOutput"]["decision"]["behavior"], "allow")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".board").mkdir()
        self.db = self.root / ".board" / "live-events.sqlite3"

    def hook(self, source, event):
        output = io.StringIO()
        payload = {"session_id": SESSION, "hook_event_name": event, "stop_hook_active": False}
        with patch.object(approval_hook, "ROOT", self.root), patch("approval_hook.sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("approval_hook.sys.stdout", output), patch("approval_hook.sys.argv", ["approval_hook.py", source.lower()]):
            approval_hook.main()
        return json.loads(output.getvalue()) if output.getvalue() else None

    def test_queued_messages_reach_the_live_session_once(self):
        from live_events import queue_message
        store = LiveEventStore(self.db)
        queue_message(self.db, KEY, "也把测试跑一下")
        queue_message(self.db, KEY, "然后提交")
        self.assertEqual([m["delivered"] for m in store.outbox(KEY)], [None, None])
        out = self.hook("Claude", "Stop")
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("也把测试跑一下", context)
        self.assertIn("然后提交", context)
        self.assertTrue(all(m["delivered"] for m in store.outbox(KEY)))
        self.assertIsNone(self.hook("Claude", "Stop"))  # nothing twice, so no endless continuation

    def test_codex_stop_continues_with_a_new_prompt_and_prompts_carry_leftovers(self):
        from live_events import queue_message
        queue_message(self.db, "codex:" + SESSION, "hello")
        out = self.hook("Codex", "Stop")
        self.assertEqual(out["decision"], "block")
        self.assertIn("hello", out["reason"])
        queue_message(self.db, KEY, "later")
        out = self.hook("Claude", "UserPromptSubmit")
        self.assertIn("later", out["hookSpecificOutput"]["additionalContext"])

    def test_queued_message_can_be_cancelled_until_delivered(self):
        from live_events import queue_message
        store = LiveEventStore(self.db)
        first = queue_message(self.db, KEY, "oops")
        self.assertTrue(store.cancel(KEY, first))
        self.assertEqual(store.outbox(KEY), [])
        second = queue_message(self.db, KEY, "keep")
        self.hook("Claude", "Stop")
        self.assertFalse(store.cancel(KEY, second))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_focus_and_settings_round_trip(self):
        self.assertEqual(load_focus(self.root), [])
        self.assertEqual(save_focus(self.root, ["claude:a", "claude:a", " ", "codex:b"]), ["claude:a", "codex:b"])
        self.assertEqual(load_focus(self.root), ["claude:a", "codex:b"])
        self.assertEqual(load_settings(self.root)["approval_wait_seconds"], 120)
        save_settings(self.root, {"approval_wait_seconds": 300})
        self.assertEqual(load_settings(self.root)["approval_wait_seconds"], 300)
        with self.assertRaises(ValueError):
            save_settings(self.root, {"approval_wait_seconds": 7})

    def test_online_marker_follows_this_process(self):
        self.assertFalse(board_online(self.root))
        mark_online(self.root)
        self.assertTrue(board_online(self.root))
        mark_offline(self.root)
        self.assertFalse(board_online(self.root))


class RunnerTests(unittest.TestCase):
    def test_resume_commands_send_text_on_stdin(self):
        with patch("agent_runner.claude_command", return_value=["claude"]), patch("agent_runner.codex_command", return_value=["codex"]):
            self.assertEqual(resume_command("Claude", "abc"), ["claude", "-p", "--resume", "abc", "--output-format", "json"])
            self.assertEqual(resume_command("Codex", "abc")[-1], "-")

    def test_send_runs_in_background_and_reports_errors(self):
        class Fake:
            def __init__(self, *args, **kwargs):
                self.returncode = 1

            def communicate(self, text, timeout=None):
                Fake.received = text
                return "", "model unavailable"

        runner = AgentRunner(popen=Fake)
        with patch("agent_runner.claude_command", return_value=["claude"]):
            runner.send("claude:x", "Claude", "x", "/no/such/folder", "  hello  ")
        for _ in range(100):
            if runner.state("claude:x")["state"] != "sending":
                break
            __import__("time").sleep(0.01)
        self.assertEqual(Fake.received, "hello")
        self.assertEqual(runner.state("claude:x")["state"], "error")
        self.assertIn("model unavailable", runner.state("claude:x")["error"])
        with self.assertRaises(ValueError):
            runner.send("claude:x", "Claude", "x", "", "   ")


class BranchTests(unittest.TestCase):
    def row(self, uuid, parent, kind, text, **extra):
        message = {"role": kind, "content": [{"type": "text", "text": text}]}
        if kind == "assistant":
            message["stop_reason"] = "end_turn"
        return {"uuid": uuid, "parentUuid": parent, "type": kind, "sessionId": SESSION,
                "timestamp": "2026-10-20T10:00:00Z", "message": message, **extra}

    def read(self, rows):
        from conversation_store import read_claude
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            return [m["text"] for m in read_claude(path).messages]

    def test_only_the_branch_the_app_shows_is_read(self):
        texts = self.read([
            self.row("a", None, "user", "hello"), self.row("b", "a", "assistant", "hi"),
            # Another process resumed the session from "b" and wrote a side branch...
            self.row("x", "b", "user", "from the board"), self.row("y", "x", "assistant", "side reply"),
            # ...then the app continued from "b" as well.
            self.row("c", "b", "user", "from the app"), self.row("d", "c", "assistant", "app reply"),
        ])
        self.assertEqual(texts, ["hello", "hi", "from the app", "app reply"])

    def test_compaction_keeps_earlier_history(self):
        texts = self.read([
            self.row("a", None, "user", "before"), self.row("b", "a", "assistant", "old"),
            {"uuid": "k", "parentUuid": None, "logicalParentUuid": "b", "type": "system", "subtype": "compact_boundary"},
            self.row("c", "k", "user", "after"),
        ])
        self.assertEqual(texts, ["before", "old", "after"])


class GuardTests(unittest.TestCase):
    def call(self, method, host, header=None):
        import asyncio
        from starlette.requests import Request
        import server
        headers = [(b"host", host.encode())] + ([(b"x-pigenthub", header.encode())] if header else [])
        request = Request({"type": "http", "method": method, "path": "/api/focus", "headers": headers})

        async def passed(_):
            return "passed"
        result = asyncio.run(server.only_this_page_can_act(request, passed))
        return result if result == "passed" else result.status_code

    def test_actions_need_the_page_header_and_a_local_host(self):
        self.assertEqual(self.call("PUT", "127.0.0.1:8001"), 403)
        self.assertEqual(self.call("PUT", "evil.example:8001", "1"), 403)
        self.assertEqual(self.call("PUT", "127.0.0.1:8001", "1"), "passed")
        self.assertEqual(self.call("GET", "evil.example:8001"), 403)
        self.assertEqual(self.call("GET", "localhost:8001"), "passed")


class MessageRoutingTests(unittest.TestCase):
    """Exercise the real route, outbox and hook together without calling a model."""
    def test_running_message_is_queued_then_handed_to_the_matching_session(self):
        import server
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "events.sqlite3"
            live = LiveEventStore(db)
            card = {"source": "Claude", "session_id": SESSION, "project": folder, "status": "running"}
            with patch.object(server.store, "detail", return_value=card), patch.object(server, "live_events", live), \
                 patch.object(live, "listeners", return_value=[{"source": "Claude", "delivery": True}]), \
                 patch.object(server.runner, "send") as send:
                response = server.send_message(KEY, server.NewMessage(text="route check"))
                self.assertTrue(response["queued"])
                send.assert_not_called()
                from live_events import take_outbox
                messages = take_outbox(db, KEY, "Stop")
                self.assertEqual(messages[0], "route check")
                output = approval_hook.delivery_output("Claude", "Stop", messages)
                self.assertIn("route check", output["hookSpecificOutput"]["additionalContext"])
                self.assertTrue(live.outbox(KEY)[0]["delivered"])

    def test_idle_send_resumes_original_id_and_missing_hooks_cannot_queue(self):
        import server
        from fastapi import HTTPException
        card = {"source": "Codex", "session_id": SESSION, "project": "/project", "status": "done"}
        with patch.object(server.store, "detail", return_value=card), patch.object(server.runner, "send") as send:
            server.send_message("codex:" + SESSION, server.NewMessage(text="hello"))
            send.assert_called_once_with("codex:" + SESSION, "Codex", SESSION, "/project", "hello")
        card["status"] = "running"
        with patch.object(server.store, "detail", return_value=card), \
             patch.object(server.live_events, "snapshot", return_value={}), \
             patch.object(server.live_events, "listeners", return_value=[]):
            with self.assertRaises(HTTPException) as error:
                server.send_message("codex:" + SESSION, server.NewMessage(text="hello"))
            self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            server.send_message(KEY, server.NewMessage(text="   "))


if __name__ == "__main__":
    unittest.main()
