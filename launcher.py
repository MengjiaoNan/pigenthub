"""Start and stop this project's local board without keeping a terminal open."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid
import webbrowser
from threading import Event, Thread

from board_runtime import APP_ID, APP_NAME, instance_id
from platform_support import background_options, venv_python

ROOT = Path(__file__).resolve().parent
PORTS = tuple(range(8001, 8011))


class LauncherError(Exception):
    pass


class Launcher:
    def __init__(self, root=ROOT, ports=PORTS):
        self.root = Path(root).resolve()
        self.directory = self.root / ".board"
        self.state_path = self.directory / "server.json"
        self.log_path = self.directory / "server.log"
        self.ports = tuple(ports)
        self.identity = instance_id(self.root)
        self.process = None
        self.http = build_opener(ProxyHandler({}))

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "launcher.lock").open("a+b") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            if sys.platform == "win32":
                import msvcrt
                def acquire():
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                def release():
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                def acquire():
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                def release():
                    fcntl.flock(handle, fcntl.LOCK_UN)
            deadline = time.monotonic() + 120
            while True:
                try:
                    acquire()
                    break
                except OSError as error:
                    if error.errno not in {11, 13, 35, 36}:
                        raise
                    if time.monotonic() >= deadline:
                        raise LauncherError("另一个启动操作仍在进行，请稍后重试。")
                    time.sleep(0.2)
            try:
                yield
            finally:
                release()

    def health(self, port):
        try:
            with self.http.open(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
                data = json.loads(response.read(8192))
            return data if isinstance(data, dict) else None
        except (OSError, URLError, ValueError):
            return None

    def ours(self, health):
        return bool(health and health.get("status") == "ok" and
                    health.get("app") == APP_ID and health.get("instance_id") == self.identity)

    def state(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if (isinstance(value, dict) and type(value.get("port")) is int and
                    0 < value["port"] < 65536 and type(value.get("pid")) is int and
                    value["pid"] > 1 and isinstance(value.get("launch_id"), str) and
                    value["launch_id"] and value.get("instance_id") == self.identity):
                return value
        except (OSError, ValueError):
            pass
        return None

    @staticmethod
    def available(port):
        with socket.socket() as probe:
            # Match uvicorn's bind behavior; recently closed connections should
            # not make an otherwise free port look occupied after a restart.
            if sys.platform == "win32":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def environment(self):
        python = venv_python(self.root)
        if not python.exists():
            print("首次启动：正在创建项目运行环境……", flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(self.root / ".venv")], check=True)
        try:
            check = subprocess.run([str(python), "-I", "-c", "import fastapi, uvicorn"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            raise LauncherError("项目的 .venv 无法使用。复制项目时请排除 .venv，再重新启动。") from error
        if check.returncode:
            print("首次启动：正在安装依赖，需要连接网络，请稍候……", flush=True)
            subprocess.run([str(python), "-m", "pip", "install", "-r", str(self.root / "requirements.txt")], check=True)
        return python

    def start(self, python=None):
        with self.locked():
            state = self.state()
            ports = list(dict.fromkeys(([state["port"]] if state else []) + list(self.ports)))
            for port in ports:
                if self.ours(self.health(port)):
                    return f"http://127.0.0.1:{port}/", False
            python = Path(python) if python else self.environment()
            for port in self.ports:
                if not self.available(port):
                    continue
                launch_id = uuid.uuid4().hex
                env = os.environ.copy()
                env.pop("PYTHONHOME", None)
                env.pop("PYTHONPATH", None)
                env["BOARD_LAUNCH_ID"] = launch_id
                # Keep all server output away from the launch terminal, and detach
                # the process so quitting that terminal cannot send it SIGHUP.
                with self.log_path.open("ab", buffering=0) as log:
                    process = subprocess.Popen(
                        [str(python), str(self.root / "launcher.py"), "_serve", "--port", str(port)],
                        cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        close_fds=True, **background_options(),
                    )
                self.process = process
                ready = False
                try:
                    deadline = time.monotonic() + 20
                    healthy = False
                    while time.monotonic() < deadline and process.poll() is None:
                        health = self.health(port)
                        # Windows venv executables can be redirector processes.
                        # The per-launch nonce identifies the server they start;
                        # its reported PID may differ from Popen.pid.
                        if (self.ours(health) and health.get("launch_id") == launch_id and
                                type(health.get("pid")) is int and health["pid"] > 0):
                            healthy = True
                            break
                        time.sleep(0.2)
                    if healthy:
                        state = {"pid": health["pid"], "port": port, "launch_id": launch_id,
                                 "instance_id": self.identity, "started_at": time.time()}
                        temporary = self.state_path.with_suffix(".tmp")
                        temporary.write_text(json.dumps(state) + "\n", encoding="utf-8")
                        temporary.replace(self.state_path)
                        ready = True
                        return f"http://127.0.0.1:{port}/", True
                finally:
                    if not ready:
                        self.terminate(process)
                # A different process may have claimed this port after our probe.
                if self.available(port):
                    raise LauncherError(f"后台启动失败，请查看日志：{self.log_path}")
            raise LauncherError("8001–8010 端口均不可用，请关闭占用这些端口的程序后重试。")

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        else:
            process.wait()

    def stop(self):
        with self.locked():
            state = self.state()
            if not state:
                return "没有找到一键启动的后台记录。手动启动的后台请在原终端按 Control+C 停止。"
            health = self.health(state["port"])
            if health is None:
                # os.kill(pid, 0) terminates a process on Windows. Retain an
                # unreachable server's record; a later start can replace it.
                raise LauncherError("暂时无法确认后台状态，已保留启动记录，请稍后重试停止。")
            if not (self.ours(health) and health.get("pid") == state["pid"] and
                    health.get("launch_id") == state["launch_id"]):
                self.state_path.unlink(missing_ok=True)
                return "记录中的看板后台已停止，已清理旧的启动记录。"
            if health.get("launcher_protocol") == 2:
                request_path = self.directory / ("stop-" + state["launch_id"] + ".request")
                request_path.touch()
            elif sys.platform != "win32":
                # Compatibility with the already-running macOS v1 launcher.
                try:
                    os.kill(state["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                raise LauncherError("后台版本较旧，请在其原启动窗口中停止后重新启动。")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                health = self.health(state["port"])
                if not (self.ours(health) and health.get("launch_id") == state["launch_id"]):
                    self.state_path.unlink(missing_ok=True)
                    (self.directory / ("stop-" + state["launch_id"] + ".request")).unlink(missing_ok=True)
                    return "看板后台已停止。下次运行启动入口即可恢复。"
                time.sleep(0.2)
            raise LauncherError(f"后台暂未退出，请查看日志：{self.log_path}")


def serve(port):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config("server:app", host="127.0.0.1", port=port, access_log=False))
    launch_id = os.environ.get("BOARD_LAUNCH_ID")
    stop = Event()
    def watch():
        while not stop.wait(0.2):
            try:
                if launch_id and (ROOT / ".board" / ("stop-" + launch_id + ".request")).is_file():
                    server.should_exit = True
                    return
            except OSError:
                pass
    thread = Thread(target=watch, daemon=True)
    thread.start()
    try:
        server.run()
    finally:
        stop.set()
        thread.join(timeout=1)


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} launcher (macOS / Linux / Windows)")
    parser.add_argument("action", nargs="?", default="start", choices=["start", "stop", "_serve"])
    parser.add_argument("--no-browser", action="store_true", help="启动后仅显示地址")
    parser.add_argument("--port", type=int, default=8001, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == "_serve":
        serve(args.port)
        return 0
    launcher = Launcher()
    try:
        if args.action == "stop":
            print(launcher.stop())
            return 0
        url, started = launcher.start()
        print((f"{APP_NAME} 已启动：" if started else f"{APP_NAME} 已在运行：") + url, flush=True)
        print("后台会继续运行，现在可以关闭这个终端窗口。")
        entry = "stop-board.bat" if sys.platform == "win32" else "停止看板.command" if sys.platform == "darwin" else "stop-board.sh"
        print(f"需要停止时，运行「{entry}」。", flush=True)
        if not args.no_browser:
            try:
                headless = sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
                opened = False if headless else webbrowser.open(url, new=2)
            except (OSError, webbrowser.Error):
                opened = False
            if not opened:
                print("浏览器未能自动打开，请复制上面的地址。")
        return 0
    except (LauncherError, OSError, subprocess.SubprocessError) as error:
        print("启动器提示：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
