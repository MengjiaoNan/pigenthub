import base64
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from install_observers import ROOT, merge_hooks, observer_handler
from live_events import LiveEventStore
from platform_support import agent_home, background_options, claude_command, hook_references, venv_python


class PlatformTests(unittest.TestCase):
    def test_venv_locations_and_detached_process_options(self):
        root = PureWindowsPath("C:/项目 folder")
        self.assertEqual(str(venv_python(root, "win32")), r"C:\项目 folder\.venv\Scripts\python.exe")
        self.assertEqual(venv_python(Path("project"), "linux"), Path("project/.venv/bin/python"))
        self.assertEqual(background_options("linux"), {"start_new_session": True})
        self.assertEqual(background_options("win32"), {"creationflags": 0x208})

    def test_windows_hooks_handle_unicode_spaces_and_quotes(self):
        root = PureWindowsPath("C:/项目's $folder")
        claude = observer_handler("Claude", "win32", root)
        self.assertEqual(claude["command"], str(venv_python(root, "win32")))
        self.assertIn(str(root / "observer_hook.py"), claude["args"])
        self.assertEqual(claude["onFailure"], "continue")
        codex = observer_handler("Codex", "win32", root)
        program = base64.b64decode(codex["command"].split()[-1]).decode("utf-16-le")
        self.assertIn("项目''s $folder", program)
        self.assertIn("[Console]::OpenStandardInput()", program)
        self.assertIn(".CopyTo($child.StandardInput.BaseStream)", program)
        self.assertIn("$child.StandardOutput.BaseStream.CopyTo", program)
        self.assertTrue(hook_references(codex, str(root / "observer_hook.py")))
        self.assertEqual(codex["command"], codex["commandWindows"])

    def test_windows_merge_is_idempotent_and_preserves_other_hooks(self):
        for source in ["Codex", "Claude"]:
            original = {"permissions": {"allow": ["Read"]}, "hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "existing-hook.exe"}]}]}}
            merged = merge_hooks(original, source, "win32")
            self.assertEqual(merge_hooks(merged, source, "win32"), merged)
            self.assertEqual(merged["permissions"], original["permissions"])
            self.assertEqual(merged["hooks"]["Stop"][0], original["hooks"]["Stop"][0])

    def test_configured_data_directories_are_used_for_listener_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ["codex", "claude"]:
                (root / name).mkdir()
            with patch.dict(os.environ, {"CODEX_HOME": str(root / "codex"), "CLAUDE_CONFIG_DIR": str(root / "claude")}):
                self.assertEqual(agent_home("Codex"), root / "codex")
                for source, name in [("Codex", "hooks.json"), ("Claude", "settings.json")]:
                    (agent_home(source) / name).write_text(json.dumps(merge_hooks({}, source, "win32")), encoding="utf-8")
                self.assertTrue(all(item["configured"] for item in LiveEventStore(root / "unused.sqlite3").listeners({})))

    def test_real_observer_command_for_the_current_os_forwards_unicode_json(self):
        with tempfile.TemporaryDirectory(prefix="board 钩子's $ ") as folder:
            root = Path(folder)
            for name in ["observer_hook.py", "live_events.py", "platform_support.py"]:
                shutil.copy2(ROOT / name, root / name)
            # Surface failures from the test fixture; installed observers stay passive.
            observer = root / "observer_hook.py"
            observer.write_text(observer.read_text(encoding="utf-8").replace(
                "        pass\n", "        raise\n"), encoding="utf-8")
            payload = {"session_id": "88fa01dd-3b81-4e8e-94f5-4d104d307a53",
                       "hook_event_name": "PermissionRequest", "tool_name": "Write",
                       "tool_input": {"description": "请求写入中文文件"}}
            for source in ["Codex", "Claude"]:
                handler = observer_handler(source, root=root, interpreter=sys.executable)
                command = [handler["command"], *handler["args"]] if "args" in handler else handler["command"]
                result = subprocess.run(command, shell=isinstance(command, str),
                                        input=json.dumps(payload, ensure_ascii=False),
                                        text=True, encoding="utf-8", capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
                records = LiveEventStore(root / ".board/live-events.sqlite3").snapshot()
                self.assertIn(source.lower() + ":" + payload["session_id"], records,
                              f"{source} did not record the forwarded JSON: {result.stderr}")
            records = LiveEventStore(root / ".board/live-events.sqlite3").snapshot()
            self.assertEqual(len(records), 2)
            for state in records.values():
                self.assertEqual(state["pending"][0]["reason"], "请求写入中文文件")

    def test_summary_cli_override_and_npm_shim_without_shell(self):
        with patch.dict(os.environ, {"BOARD_CLAUDE_CLI": "custom-claude"}):
            self.assertEqual(claude_command(), ["custom-claude"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            entry = path / "node_modules/@anthropic-ai/claude-code/cli.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("// test only", encoding="utf-8")
            with patch("platform_support.shutil.which", return_value="node"):
                self.assertEqual(claude_command(path / "claude.cmd"), ["node", str(entry)])


if __name__ == "__main__":
    unittest.main()
