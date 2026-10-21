"""Small JSON files under .board: user settings, focused conversations, and the server heartbeat."""
import json
import os
from pathlib import Path

DEFAULTS = {"approval_wait_seconds": 120}
WAIT_CHOICES = (30, 60, 120, 300, 540)
FOCUS_LIMIT = 30


def board_dir(root):
    return Path(root) / ".board"


def read_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_settings(root):
    saved = read_json(board_dir(root) / "settings.json", {})
    wait = saved.get("approval_wait_seconds")
    return {"approval_wait_seconds": wait if wait in WAIT_CHOICES else DEFAULTS["approval_wait_seconds"]}


def save_settings(root, values):
    settings = load_settings(root)
    wait = values.get("approval_wait_seconds")
    if wait is not None:
        if wait not in WAIT_CHOICES:
            raise ValueError("This wait duration is not supported.")
        settings["approval_wait_seconds"] = wait
    write_json(board_dir(root) / "settings.json", settings)
    return settings


def load_focus(root):
    """Conversation ids (like "claude:<uuid>") pinned to the Focus list, in the user's order."""
    ids = read_json(board_dir(root) / "focus.json", {}).get("conversations", [])
    return [i for i in ids if isinstance(i, str) and i][:FOCUS_LIMIT]


def save_focus(root, ids):
    clean = []
    for item in ids:
        if isinstance(item, str) and item.strip() and item.strip() not in clean:
            clean.append(item.strip()[:200])
    if len(clean) > FOCUS_LIMIT:
        raise ValueError(f"You can focus on up to {FOCUS_LIMIT} conversations.")
    write_json(board_dir(root) / "focus.json", {"conversations": clean})
    return clean


def mark_online(root):
    write_json(board_dir(root) / "answering.json", {"pid": os.getpid()})


def mark_offline(root):
    path = board_dir(root) / "answering.json"
    if read_json(path, {}).get("pid") == os.getpid():
        path.unlink(missing_ok=True)


def board_online(root):
    """True only while a board server from this folder is running, so hooks never wait for nobody."""
    pid = read_json(board_dir(root) / "answering.json", {}).get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True
