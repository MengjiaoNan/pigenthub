import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from platform_support import claude_command


def run_claude(on_event, prompt):
    run_id = str(uuid4())
    session_id = None

    def emit(event_type, message):
        on_event({
            "agent_id": "claude",
            "session_id": session_id,
            "run_id": run_id,
            "type": event_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request": None,
        })

    emit("run_started", "Waiting for Claude Code to respond")

    process = subprocess.run(
        [
            *claude_command(),
            "-p", prompt,
            "--output-format", "json",
            "--tools", "",
            "--disallowedTools", "mcp__*",
        ],
        cwd=Path(__file__).parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    if process.returncode != 0:
        error = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(error or "Claude Code failed.")

    result = json.loads(process.stdout)

    if result.get("is_error"):
        raise RuntimeError(result.get("result") or "Claude returned an error.")

    reply = result.get("result")
    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError("Claude did not return a text reply.")

    session_id = result.get("session_id")
    emit("run_completed", reply)
