from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
from threading import Thread
import unittest
from unittest.mock import Mock, patch

from launcher import Launcher, LauncherError, ROOT
from board_runtime import APP_ID


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LauncherReadinessTests(unittest.TestCase):
    def test_venv_redirector_uses_the_verified_server_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Launcher(Path(folder), ports=[8001])
            redirector = Mock(pid=101)
            redirector.poll.return_value = None
            with patch("launcher.subprocess.Popen", return_value=redirector) as spawn:
                def health(port):
                    if spawn.call_args is None:
                        return None
                    return {"status": "ok", "app": APP_ID, "instance_id": launcher.identity,
                            "launch_id": spawn.call_args.kwargs["env"]["BOARD_LAUNCH_ID"], "pid": 202}
                with patch.object(launcher, "health", side_effect=health), \
                        patch.object(launcher, "available", return_value=True):
                    self.assertEqual(launcher.start(python=sys.executable), ("http://127.0.0.1:8001/", True))
            self.assertEqual(launcher.state()["pid"], 202)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="board launcher 含空格 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Exercise the real uvicorn process with isolated runtime files and logs.
        for name in ["launcher.py", "board_runtime.py", "platform_support.py", "server.py", "summaries.py",
                     "conversation_store.py", "native_links.py", "list_sessions.py",
                     "live_events.py", "agent_runner.py", "board_settings.py", "workbench.html"]:
            shutil.copy2(ROOT / name, self.root / name)
        shutil.copytree(ROOT / "assets", self.root / "assets")
        self.port = free_port()
        self.launcher = Launcher(self.root, ports=[self.port])
        self.addCleanup(self.cleanup_server)
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex"),
                                     "CLAUDE_CONFIG_DIR": str(self.root / "claude")})
        env.start()
        self.addCleanup(env.stop)

    def cleanup_server(self):
        process = self.launcher.process
        if process is not None:
            self.launcher.terminate(process)

    def foreign_server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps({"status": "ok", "mode": "observer",
                                   "app": "some-other-program", "pid": os.getpid()}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_real_start_repeat_and_stop_from_path_with_spaces(self):
        url, started = self.launcher.start(python=sys.executable)
        self.assertTrue(started)
        original = self.launcher.state()
        self.assertEqual(url, f"http://127.0.0.1:{self.port}/")
        self.assertTrue(self.launcher.ours(self.launcher.health(self.port)))
        second = Launcher(self.root, ports=[self.port])
        with patch.object(second, "environment", side_effect=AssertionError("must reuse server")):
            self.assertEqual(second.start(), (url, False))
        self.assertEqual(second.state()["pid"], original["pid"])
        self.assertIn("已停止", second.stop())
        self.launcher.process.wait(timeout=5)
        self.assertIsNone(self.launcher.health(self.port))
        self.assertFalse(second.state_path.exists())

    def test_busy_port_uses_another_port_and_leaves_other_program_running(self):
        busy = self.foreign_server()
        self.launcher.ports = (busy, self.port)
        url, started = self.launcher.start(python=sys.executable)
        self.assertTrue(started)
        self.assertEqual(url, f"http://127.0.0.1:{self.port}/")
        self.assertIn("已停止", self.launcher.stop())
        self.launcher.process.wait(timeout=5)
        self.assertEqual(self.launcher.health(busy)["app"], "some-other-program")

    def test_two_simultaneous_starts_share_one_process(self):
        other = Launcher(self.root, ports=[self.port])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda launcher: launcher.start(python=sys.executable),
                                    [self.launcher, other]))
        if other.process is not None:
            self.launcher.process = other.process
        self.assertEqual(sum(started for _, started in results), 1)
        self.assertEqual(results[0][0], results[1][0])
        self.assertIn("已停止", self.launcher.stop())
        self.launcher.process.wait(timeout=5)

    def test_stale_state_cannot_stop_unrelated_server(self):
        port = self.foreign_server()
        self.launcher.directory.mkdir()
        self.launcher.state_path.write_text(json.dumps({"port": port, "pid": os.getpid(),
            "launch_id": "old-launch", "instance_id": self.launcher.identity}))
        with patch("launcher.os.kill", side_effect=AssertionError("unrelated process signalled")):
            self.assertIn("旧的启动记录", self.launcher.stop())
        self.assertIsNotNone(self.launcher.health(port))

    def test_unresponsive_server_keeps_state_for_a_later_retry(self):
        self.launcher.directory.mkdir()
        self.launcher.state_path.write_text(json.dumps({"port": self.port, "pid": os.getpid(),
            "launch_id": "old-launch", "instance_id": self.launcher.identity}))
        with patch("launcher.os.kill") as kill:
            with self.assertRaises(LauncherError):
                self.launcher.stop()
        kill.assert_not_called()
        self.assertTrue(self.launcher.state_path.exists())

    def test_stop_file_must_match_the_running_launch(self):
        self.launcher.start(python=sys.executable)
        (self.launcher.directory / "stop-different-launch.request").touch()
        time.sleep(0.5)
        self.assertTrue(self.launcher.ours(self.launcher.health(self.port)))
        with patch("launcher.os.kill", side_effect=AssertionError("new servers use graceful shutdown")):
            self.assertIn("已停止", self.launcher.stop())
        self.launcher.process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
