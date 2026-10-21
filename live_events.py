"""Hook observations plus a small mailbox for answers given on the board.

Observers only record. The approval hook additionally waits for an answer the
user typed into the board; if none arrives in time, the agent's own prompt
takes over unchanged.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from time import sleep, time
from uuid import UUID
from platform_support import agent_home, hook_references

PENDING_WINDOW = 30 * 60
COMPACTION_WINDOW = 30 * 60
QUESTION_TOOLS = {"AskUserQuestion", "request_user_input"}
CLEAR_EVENTS = {"UserPromptSubmit", "Stop", "SessionEnd", "Interrupt"}
ACTIONS = {"permission": {"allow", "deny", "reply", "stop"}, "question": {"reply", "stop"}}
ANSWER_EVENTS = {
    "allow": "You allowed this request on the board", "deny": "You denied this request on the board",
    "reply": "You replied on the board: ", "stop": "You stopped this turn on the board",
}


def identifier(payload):
    # Codex's transcript filename carries the thread UUID even when a runtime
    # session has a different ID. Claude filenames use their CLI session UUID.
    path = str(payload.get("transcript_path") or "")
    match = re.search(r"([0-9a-fA-F-]{36})\.jsonl$", path)
    value = match.group(1) if match else payload.get("session_id")
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def session_key(source, payload):
    sid = identifier(payload)
    return source.lower() + ":" + sid if sid and source in {"Codex", "Claude"} else None


def fingerprint(payload):
    data = payload.get("tool_input")
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in {"description", "justification"}}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def matches_request(pending, payload, tool, digest):
    turn, use_id = payload.get("turn_id"), payload.get("tool_use_id")
    if turn and pending.get("turn_id") and turn != pending["turn_id"]:
        return False
    if use_id and pending.get("tool_use_id"):
        return use_id == pending["tool_use_id"]
    return pending.get("tool") == tool and pending.get("fingerprint") == digest


def connect(path, timeout=0.5):
    db = sqlite3.connect(path, timeout=timeout)
    db.execute("CREATE TABLE IF NOT EXISTS live_sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS decisions (request_id TEXT PRIMARY KEY, session TEXT NOT NULL, action TEXT NOT NULL, message TEXT NOT NULL, created REAL NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL, delivered REAL, via TEXT)")
    return db


def queue_message(path, key, text, now=None):
    """Board side: hold a message until the live agent session can take it."""
    now = time() if now is None else now
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path, timeout=2)) as db, db:
        return db.execute("INSERT INTO outbox (session, text, created) VALUES (?, ?, ?)", (key, text, now)).lastrowid


def take_outbox(path, key, via, now=None):
    """Hook side: hand every waiting message for this session to the agent, oldest first."""
    now = time() if now is None else now
    if not Path(path).exists():
        return []
    with closing(connect(path, timeout=2)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id, text FROM outbox WHERE session=? AND delivered IS NULL ORDER BY id", (key,)).fetchall()
        if rows:
            db.execute(f"UPDATE outbox SET delivered=?, via=? WHERE id IN ({','.join('?' * len(rows))})",
                       (now, via, *[r[0] for r in rows]))
        return [r[1] for r in rows]


def delivery_text(messages):
    body = "\n\n---\n\n".join(messages)
    return ("The user sent you this from PigentHub (their agent board) while you were working. "
            "Treat it exactly like a new message from them:\n\n" + body)


def stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def load_state(db, key):
    row = db.execute("SELECT state FROM live_sessions WHERE id=?", (key,)).fetchone()
    return json.loads(row[0]) if row else {"pending": [], "events": []}


def save_state(db, key, source, state, now):
    state["events"] = state["events"][-30:]
    db.execute("INSERT OR REPLACE INTO live_sessions VALUES (?, ?, ?, ?)",
               (key, source, json.dumps(state, ensure_ascii=False), now))


def record_hook(path, source, payload, now=None, request_id=None, answer_until=None):
    """Record one hook event. With request_id, the new pending request can be answered on the board until answer_until."""
    if source not in {"Codex", "Claude"} or not isinstance(payload, dict):
        return False
    key = session_key(source, payload)
    if not key:
        return False
    kind = payload.get("hook_event_name")
    tool = str(payload.get("tool_name") or "")[:120]
    short_tool = tool.rsplit(".", 1)[-1]
    if kind == "PreToolUse" and short_tool not in QUESTION_TOOLS:
        return False
    notification = payload.get("notification_type")
    if kind == "Notification" and notification not in {"permission_prompt", "elicitation_dialog", "elicitation_url_dialog"}:
        return False
    if kind not in CLEAR_EVENTS | {"SessionStart", "PermissionRequest", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Notification", "PreCompact", "PostCompact"}:
        return False
    now = time() if now is None else now
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        state = load_state(db, key)
        pending = state["pending"]
        description = None
        if kind == "PreCompact":
            # Compaction can occur while another tool still needs approval.
            state["compaction"] = {"started_at": now, "turn_id": payload.get("turn_id")}
            description = "Compacting context"
        elif kind == "PostCompact":
            current = state.get("compaction") or {}
            if not (current.get("turn_id") and payload.get("turn_id") and current["turn_id"] != payload["turn_id"]):
                state.pop("compaction", None)
            description = "Context compaction completed"
        elif kind == "SessionStart":
            # Resume/reconnect is not evidence that a pending request ended.
            state.pop("compaction", None)
            description = "Conversation updated"
        elif kind in CLEAR_EVENTS:
            state.pop("compaction", None)
            pending.clear()
            description = {"Stop": "Agent finished responding", "Interrupt": "Interrupted", "SessionEnd": "Conversation closed"}.get(kind, "Conversation updated")
        elif kind in {"PostToolUse", "PostToolUseFailure"}:
            state.pop("compaction", None)
            digest = fingerprint(payload)
            matching = [p for p in pending if matches_request(p, payload, tool, digest)]
            # A generic network permission notification has no tool identity.
            generic = [p for p in pending if p.get("generic")]
            for p in matching + generic:
                if p in pending:
                    pending.remove(p)
            if matching or generic:
                description = "Tool result received · request resolved"
        else:
            state.pop("compaction", None)
            data = payload.get("tool_input")
            data = data if isinstance(data, dict) else {}
            question = kind == "PreToolUse" or notification in {"elicitation_dialog", "elicitation_url_dialog"}
            reason = data.get("description") or data.get("justification") or payload.get("message")
            if question and isinstance(data.get("questions"), list):
                reason = "; ".join(str(q.get("question", "")) for q in data["questions"] if isinstance(q, dict))
            if not reason and isinstance(data.get("command"), str):
                reason = tool + ": " + data["command"]
            reason = str(reason or ((tool or source) + (" is waiting for your answer" if question else " needs permission")))[:240]
            generic = kind == "Notification"
            # Notification often repeats an already observed PermissionRequest.
            if not (generic and pending):
                digest = fingerprint(payload)
                pending[:] = [p for p in pending if not matches_request(p, payload, tool, digest)]
                pending.append({"kind": "question" if question else "permission", "reason": reason,
                                "tool": tool, "tool_use_id": payload.get("tool_use_id"),
                                "turn_id": payload.get("turn_id"),
                                "fingerprint": digest, "received_at": now, "generic": generic,
                                "request_id": request_id, "answer_until": answer_until if request_id else None})
            description = "Waiting for an answer: " + reason if question else "Approval requested: " + reason
        state["last_event"], state["last_seen"] = kind, now
        if description:
            state["events"].append({"message": description, "timestamp": stamp(now)})
        save_state(db, key, source, state, now)
    return True


def submit_decision(path, key, request_id, action, message="", now=None):
    """Board side: leave an answer for a waiting hook. Returns an error message, or None on success."""
    now = time() if now is None else now
    message = (message or "").strip()[:4000]
    if action == "reply" and not message:
        return "Write a reply first."
    path = Path(path)
    if not path.exists():
        return "This request has already ended."
    with closing(connect(path, timeout=2)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT source FROM live_sessions WHERE id=?", (key,)).fetchone()
        state = load_state(db, key)
        entry = next((p for p in state["pending"] if request_id and p.get("request_id") == request_id), None)
        if row is None or entry is None:
            return "This request has already ended."
        if action not in ACTIONS.get(entry["kind"], set()):
            return "That action isn't available for this request."
        if db.execute("SELECT 1 FROM decisions WHERE request_id=?", (request_id,)).fetchone():
            return "This request was already answered."
        if not entry.get("answer_until") or entry["answer_until"] < now:
            return "Time's up for answering here. Please answer in the agent app."
        db.execute("DELETE FROM decisions WHERE created < ?", (now - 86400,))
        db.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, ?)", (request_id, key, action, message, now))
        entry["answer_until"], entry["answered"] = None, action
        save_state(db, key, row[0], state, now)
    return None


def take_decision(path, key, request_id, give_up=False, now=None):
    """Hook side: return the board's answer and close the request.

    With give_up and no answer yet, the request is handed back to the agent's
    own prompt so a late click on the board can no longer race it.
    """
    now = time() if now is None else now
    with closing(connect(path, timeout=2)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        found = db.execute("SELECT action, message FROM decisions WHERE request_id=?", (request_id,)).fetchone()
        if not found and not give_up:
            return None
        row = db.execute("SELECT source FROM live_sessions WHERE id=?", (key,)).fetchone()
        state = load_state(db, key)
        entry = next((p for p in state["pending"] if p.get("request_id") == request_id), None)
        if found:
            action, message = found
            if entry:
                state["pending"].remove(entry)
            text = ANSWER_EVENTS[action] + (message[:200] if action == "reply" else "")
        else:
            if entry:
                entry["answer_until"], entry["handed_back"] = None, True
            text = "No answer on the board in time · handed back to the agent app"
        state["events"].append({"message": text, "timestamp": stamp(now)})
        if row:
            save_state(db, key, row[0], state, now)
    return {"action": found[0], "message": found[1]} if found else None


def wait_for_decision(path, key, request_id, deadline, interval=0.4, clock=time, pause=sleep):
    while clock() < deadline:
        try:
            decision = take_decision(path, key, request_id)
        except sqlite3.Error:
            decision = None
        if decision:
            return decision
        pause(interval)
    return take_decision(path, key, request_id, give_up=True)


class LiveEventStore:
    def __init__(self, path):
        self.path = Path(path)

    def snapshot(self):
        if not self.path.exists():
            return {}
        try:
            with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)) as db:
                return {key: json.loads(state) for key, state in db.execute("SELECT id, state FROM live_sessions")}
        except (OSError, sqlite3.Error, ValueError):
            return {}

    def respond(self, key, request_id, action, message=""):
        return submit_decision(self.path, key, request_id, action, message)

    def queue(self, key, text):
        return queue_message(self.path, key, text)

    def outbox(self, key, limit=50):
        if not self.path.exists():
            return []
        try:
            with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)) as db:
                rows = db.execute("SELECT id, text, created, delivered, via FROM outbox WHERE session=? ORDER BY id DESC LIMIT ?",
                                  (key, limit)).fetchall()
        except (OSError, sqlite3.Error):
            return []
        return [{"id": i, "text": t, "created": c, "delivered": d, "via": v} for i, t, c, d, v in reversed(rows)]

    def cancel(self, key, message_id):
        with closing(connect(self.path, timeout=2)) as db, db:
            return db.execute("DELETE FROM outbox WHERE id=? AND session=? AND delivered IS NULL", (message_id, key)).rowcount > 0

    def listeners(self, records):
        result = []
        for source, path in [("Codex", agent_home("Codex") / "hooks.json"), ("Claude", agent_home("Claude") / "settings.json")]:
            configured = answering = delivery = False
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
                handlers = [h for groups in config.get("hooks", {}).values() for group in groups for h in group.get("hooks", [])]
                configured = any(hook_references(h) or hook_references(h, "approval_hook.py") for h in handlers)
                answering = any(hook_references(h, "approval_hook.py") for h in handlers)
                delivery = any(hook_references(h, "approval_hook.py")
                               for event in ("Stop", "UserPromptSubmit")
                               for group in config.get("hooks", {}).get(event, [])
                               for h in group.get("hooks", []))
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            last_seen = max((s.get("last_seen", 0) for key, s in records.items() if key.startswith(source.lower() + ":")), default=0)
            result.append({"source": source, "configured": configured, "answering": answering,
                           "delivery": delivery, "last_seen": last_seen or None})
        return result

    @staticmethod
    def overlay(card, state, now=None):
        if not state:
            return card
        now = time() if now is None else now
        terminal = card.get("finished_at")
        terminal = datetime.fromisoformat(terminal).timestamp() if terminal else 0
        started = card.get("started_at")
        started = datetime.fromisoformat(started).timestamp() if started else 0
        compaction = state.get("compaction") or {}
        compact_at = compaction.get("started_at", 0)
        activity = card.get("activity_at")
        activity = datetime.fromisoformat(activity).timestamp() if activity else 0
        if compact_at and compact_at >= max(terminal, started, activity):
            if now - compact_at <= COMPACTION_WINDOW:
                if card["status"] in {"done", "cancelled", "failed"} or not card.get("started_at"):
                    card["started_at"] = stamp(compact_at)
                card.update(status="running", status_reason="Compacting context", activity_phase="compacting",
                            finished_at=None, activity_at=stamp(compact_at))
                card["updated_at"] = max(card.get("updated_at") or "", stamp(compact_at))
            else:
                card.update(status="unknown", status_reason="No follow-up after context compaction. Check the agent app.")
        pending = [p for p in state.get("pending", []) if p["received_at"] >= max(terminal, started)]
        requests = []
        for p in pending:
            answerable = bool(p.get("request_id") and p.get("answer_until") and p["answer_until"] > now)
            requests.append({"kind": p["kind"], "reason": p["reason"], "received_at": p["received_at"],
                             "request_id": p.get("request_id") if answerable else None,
                             "answerable": answerable, "answer_until": p.get("answer_until") if answerable else None,
                             "answered": p.get("answered"), "handed_back": bool(p.get("handed_back")),
                             "actions": sorted(ACTIONS[p["kind"]]) if answerable else []})
        card["pending_requests"] = requests
        if pending:
            newest = max(p["received_at"] for p in pending)
            if now - newest > PENDING_WINDOW:
                card["status"], card["status_reason"] = "unknown", "The previous request is stale. Check the original app for its current status."
            elif any(r["answered"] for r in requests):
                card["status"], card["status_reason"] = "needs_you", "Answer sent. Waiting for the agent to continue."
            elif any(r["answerable"] for r in requests):
                card["status"], card["status_reason"] = "needs_you", "Answer right here on the card. If the timer runs out, the request moves back to the agent app."
            else:
                card["status"] = "needs_you"
                card["status_reason"] = "Waiting for your approval or answer in the original app. Updates when the tool returns."
        return card
