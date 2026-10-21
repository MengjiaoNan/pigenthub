"""Prepare/merge board hooks; never writes trust or permission rules.

Most events are observed only. PermissionRequest and question events use
approval_hook.py, which can pass on an answer you give on the board.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from platform_support import agent_home, hook_references, venv_python

ROOT = Path(__file__).resolve().parent
BASE_EVENTS = ["PermissionRequest", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"]


ANSWER_EVENTS = {"PermissionRequest", "PreToolUse"}
ANSWER_TIMEOUT = 600
# These events deliver messages queued on the board; they never wait.
DELIVERY_EVENTS = {"Stop", "UserPromptSubmit"}
DELIVERY_TIMEOUT = 10


def observer_handler(source, platform=None, root=ROOT, interpreter=None, script_name="observer_hook.py", timeout=3):
    platform = platform or sys.platform
    python, script = str(interpreter or venv_python(root, platform)), str(root / script_name)
    if platform != "win32":
        return {"type": "command", "command": shlex.quote(python) + " " + shlex.quote(script) + " " + source.lower(), "timeout": timeout}
    args = ["-X", "utf8", script, source.lower()]
    if source == "Claude":
        return {"type": "command", "command": python, "args": args,
                "timeout": timeout, "onFailure": "continue"}
    # A shell-neutral outer command works through cmd, PowerShell and Git Bash.
    # Forward bytes directly: Windows PowerShell's text pipeline can change
    # native-command stdin. Python handles UTF-8 via the explicit -X option.
    executable = "'" + python.replace("'", "''") + "'"
    arguments = "'" + subprocess.list2cmdline(args).replace("'", "''") + "'"
    program = ("$start = [System.Diagnostics.ProcessStartInfo]::new(); "
               "$start.FileName = " + executable + "; $start.Arguments = " + arguments + "; "
               "$start.UseShellExecute = $false; $start.CreateNoWindow = $true; "
               "$start.RedirectStandardInput = $true; $start.RedirectStandardOutput = $true; "
               "$child = [System.Diagnostics.Process]::Start($start); "
               "[Console]::OpenStandardInput().CopyTo($child.StandardInput.BaseStream); "
               "$child.StandardInput.BaseStream.Close(); "
               "$child.StandardOutput.BaseStream.CopyTo([Console]::OpenStandardOutput()); "
               "$child.WaitForExit(); $exitCode = $child.ExitCode; $child.Dispose(); exit $exitCode")
    command = "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(program.encode("utf-16-le")).decode("ascii")
    return {"type": "command", "command": command, "commandWindows": command, "timeout": timeout}


def merge_hooks(data, source, platform=None):
    result = json.loads(json.dumps(data))
    hooks = result.setdefault("hooks", {})
    events = BASE_EVENTS + (["Interrupt", "PreCompact", "PostCompact"] if source == "Codex" else ["PostToolUseFailure", "Notification"])
    for event in events + ["PreToolUse"]:
        groups = hooks.setdefault(event, [])
        # Only replace our own handler. Keep all other custom hooks and settings.
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if not any(
                hook_references(h, str(ROOT / name)) for name in ("observer_hook.py", "approval_hook.py"))]
        groups[:] = [g for g in groups if g.get("hooks")]
        # Approval and question events wait for an answer from the board; the rest only observe.
        if event in ANSWER_EVENTS:
            handler = observer_handler(source, platform, script_name="approval_hook.py", timeout=ANSWER_TIMEOUT)
        elif event in DELIVERY_EVENTS:
            handler = observer_handler(source, platform, script_name="approval_hook.py", timeout=DELIVERY_TIMEOUT)
        else:
            handler = observer_handler(source, platform)
        entry = {"hooks": [handler]}
        if event == "Notification":
            entry["matcher"] = "permission_prompt|elicitation_dialog|elicitation_url_dialog"
        elif event == "PreToolUse":
            entry["matcher"] = "AskUserQuestion|request_user_input"
        groups.append(entry)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--source", choices=["codex", "claude", "both"], default="both",
                        help="Update only the selected agent's configuration")
    args = parser.parse_args()
    backup = ROOT / ".board" / "hook-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    targets = [("Codex", agent_home("Codex") / "hooks.json"), ("Claude", agent_home("Claude") / "settings.json")]
    if args.source != "both":
        targets = [(source, path) for source, path in targets if source.lower() == args.source]
    prepared = []
    for source, path in targets:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        prepared.append((source, path, merge_hooks(data, source)))
    if not args.install:
        for source, path, data in prepared:
            preview = ROOT / ".board" / (source.lower() + "-observer-config.json")
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(source + " configuration preview: " + str(preview))
        return
    for source, path, data in prepared:
        if path.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup / (source.lower() + "-" + path.name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(source + " observer configuration saved: " + str(path))
    marker = ROOT / ".board" / "observer-install.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"installed_at": datetime.now(timezone.utc).isoformat(), "sources": [s for s, _, _ in prepared]}) + "\n", encoding="utf-8")
    if any(source == "Codex" for source, _, _ in prepared):
        print("In Codex, review and trust the new hooks using /hooks, then reopen the original conversation.")
    if any(source == "Claude" for source, _, _ in prepared):
        print("You may need to reopen existing Claude conversations.")


if __name__ == "__main__":
    main()
