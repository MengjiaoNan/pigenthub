"""Board hook: answers and messages from the board reach the live agent session.

PermissionRequest / questions: record the request, then wait (only while the
board is running) for an answer typed into the board. No answer in time, any
error, or no board means no output, so the agent shows its own prompt as before.

Stop / UserPromptSubmit: hand over messages queued while the agent was working
as hook context. This does not acknowledge their display in the desktop app.
"""
import json
from pathlib import Path
import sys
from time import time
from uuid import uuid4

from board_settings import board_online, load_settings
from live_events import delivery_text, record_hook, session_key, take_outbox, wait_for_decision

ROOT = Path(__file__).resolve().parent
STOP_TEXT = "The user stopped this task from PigentHub. Do not continue; end your turn now."


def hook_output(source, event, decision):
    action, message = decision["action"], (decision.get("message") or "").strip()
    if event == "PermissionRequest":
        if action == "allow":
            return {"hookSpecificOutput": {"hookEventName": event, "decision": {"behavior": "allow"}}}
        text = {
            "deny": "The user denied this request from PigentHub.",
            "reply": "The user did not approve this action. Their reply from PigentHub: " + message,
            "stop": STOP_TEXT,
        }[action]
        if action == "deny" and message:
            text += " Note from the user: " + message
        decision_body = {"behavior": "deny", "message": text}
        if action == "stop" and source == "Claude":
            # Codex reserves "interrupt" and fails closed on it.
            decision_body["interrupt"] = True
        return {"hookSpecificOutput": {"hookEventName": event, "decision": decision_body}}
    reason = STOP_TEXT if action == "stop" else (
        "The user answered this question in PigentHub instead of the dialog. Their answer: " + message)
    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                     "permissionDecisionReason": reason}}
    if action == "stop" and source == "Claude":
        output.update({"continue": False, "stopReason": "Stopped from PigentHub"})
    return output


def delivery_output(source, event, messages):
    """Pass queued messages to the live agent; desktop chat display is unconfirmed."""
    text = delivery_text(messages)
    if event == "Stop" and source == "Claude":
        # Continues the turn as context, not as a normal user chat bubble.
        return {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": text}}
    if event == "Stop":
        # Codex turns the reason into a new user prompt.
        return {"decision": "block", "reason": text}
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def main():
    try:
        source = {"codex": "Codex", "claude": "Claude"}.get(sys.argv[1])
        payload = json.load(sys.stdin)
        database = ROOT / ".board" / "live-events.sqlite3"
        event = payload.get("hook_event_name") if isinstance(payload, dict) else None
        key = session_key(source, payload) if source and isinstance(payload, dict) else None
        if key and event in {"Stop", "UserPromptSubmit"}:
            record_hook(database, source, payload)
            messages = take_outbox(database, key, via=event)
            if messages:
                sys.stdout.write(json.dumps(delivery_output(source, event, messages), ensure_ascii=False))
            return
        if not key or event not in {"PermissionRequest", "PreToolUse"} or not board_online(ROOT):
            record_hook(database, source, payload)
            return
        request_id = uuid4().hex
        deadline = time() + load_settings(ROOT)["approval_wait_seconds"]
        if not record_hook(database, source, payload, request_id=request_id, answer_until=deadline):
            return
        decision = wait_for_decision(database, key, request_id, deadline)
        if decision:
            sys.stdout.write(json.dumps(hook_output(source, event, decision), ensure_ascii=False))
    except Exception:
        # Never block or decide for the agent because the board failed.
        pass


if __name__ == "__main__":
    main()
