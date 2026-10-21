"""Small platform adapters shared by launchers, hooks and CLI integrations."""
import base64
import os
from pathlib import Path, PurePath
import shutil
import sys


def venv_python(root, platform=None):
    root = root if isinstance(root, PurePath) else Path(root)
    return root / (".venv/Scripts/python.exe" if (platform or sys.platform) == "win32"
                         else ".venv/bin/python")


def agent_home(source):
    key, default = ("CODEX_HOME", ".codex") if source == "Codex" else ("CLAUDE_CONFIG_DIR", ".claude")
    return Path(os.environ.get(key, str(Path.home() / default))).expanduser()


def background_options(platform=None):
    if (platform or sys.platform) == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (not CREATE_NEW_CONSOLE).
        return {"creationflags": 0x00000008 | 0x00000200}
    return {"start_new_session": True}


def hook_references(handler, script="observer_hook.py"):
    parts = [str(handler.get(k, "")) for k in ("command", "commandWindows", "command_windows")]
    parts.extend(str(arg) for arg in handler.get("args", []))
    for command in list(parts):
        tokens = command.split()
        if "-EncodedCommand" in tokens:
            try:
                payload = tokens[tokens.index("-EncodedCommand") + 1]
                if len(payload) < 32768:
                    parts.append(base64.b64decode(payload, validate=True).decode("utf-16-le"))
            except (ValueError, IndexError, UnicodeError):
                pass
    # PowerShell escapes a quote within single quotes by doubling it.
    return any(script in part or script.replace("'", "''") in part for part in parts)


def codex_command(executable=None):
    candidate = executable or os.environ.get("BOARD_CODEX_CLI") or shutil.which("codex")
    if not candidate:
        # The Codex desktop app ships its CLI inside the Codex home folder.
        name = "codex.exe" if sys.platform == "win32" else "codex"
        bundled = agent_home("Codex") / "plugins/.plugin-appserver/codex-cli/bin" / name
        if not bundled.is_file():
            raise RuntimeError("找不到 Codex CLI，请安装 Codex，或用 BOARD_CODEX_CLI 指定路径")
        candidate = str(bundled)
    return [str(Path(candidate).expanduser())]


def claude_command(executable=None):
    candidate = executable or os.environ.get("BOARD_CLAUDE_CLI")
    if not candidate:
        native = Path.home() / ".local/bin" / ("claude.exe" if sys.platform == "win32" else "claude")
        candidate = str(native) if native.is_file() else shutil.which("claude") or "claude"
    path = Path(candidate).expanduser()
    if path.suffix.lower() in {".cmd", ".bat"}:
        # Invoke the npm package via node, never send arguments through cmd.exe.
        entry = path.parent / "node_modules/@anthropic-ai/claude-code/cli.js"
        node = shutil.which("node")
        if entry.is_file() and node:
            return [node, str(entry)]
        raise RuntimeError("请安装原生 Claude Code CLI，或用 BOARD_CLAUDE_CLI 指定 claude.exe 路径")
    return [str(path)]
