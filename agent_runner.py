"""Continue an existing conversation with a new message, using the agent's own CLI.

The CLI resumes the same session and writes to the same local transcript, so
the board picks up the reply through its normal scan. Approvals it needs go
through the approval hook, so they appear in Needs you.
"""
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread
from time import time

from platform_support import background_options, claude_command, codex_command

RUN_TIMEOUT = 60 * 60
MESSAGE_LIMIT = 20000


def resume_command(source, session_id):
    if source == "Claude":
        # The prompt arrives on stdin, so private text never appears in process lists.
        return [*claude_command(), "-p", "--resume", session_id, "--output-format", "json"]
    if source == "Codex":
        return [*codex_command(), "exec", "resume", "--skip-git-repo-check", session_id, "-"]
    raise ValueError("This source is not supported.")


class AgentRunner:
    def __init__(self, popen=subprocess.Popen):
        self.popen = popen
        self.lock = Lock()
        self.runs = {}

    def state(self, key):
        with self.lock:
            run = self.runs.get(key)
            return dict(run) if run else None

    def send(self, key, source, session_id, project, text):
        text = (text or "").strip()
        if not text:
            raise ValueError("Write a message first.")
        if len(text) > MESSAGE_LIMIT:
            raise ValueError("This message is too long. Send it in smaller parts.")
        command = resume_command(source, session_id)
        folder = Path(project) if project and Path(project).is_dir() else Path.home()
        with self.lock:
            if self.runs.get(key, {}).get("state") == "sending":
                raise ValueError("Your previous message is still being processed.")
            self.runs[key] = {"state": "sending", "started_at": time(), "error": None}
        Thread(target=self._run, args=(key, command, folder, text), daemon=True,
               name="board-send-" + key).start()

    def _run(self, key, command, folder, text):
        error = None
        try:
            # Don't pass on the variables of an agent app this server may have been started from.
            env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_", "CODEX_INTERNAL"))}
            process = self.popen(command, cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
                                 **({"creationflags": 0x08000000} if sys.platform == "win32" else background_options()))
            try:
                stdout, stderr = process.communicate(text, timeout=RUN_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise RuntimeError("Stopped after exceeding the one-hour runtime limit.") from None
            if process.returncode:
                error = (stderr or stdout or "").strip()[-400:] or "The agent returned an error."
        except Exception as exc:
            error = str(exc) or "Failed to send the message."
        with self.lock:
            self.runs[key] = {"state": "error" if error else "sent", "started_at": self.runs[key]["started_at"],
                              "finished_at": time(), "error": error}
