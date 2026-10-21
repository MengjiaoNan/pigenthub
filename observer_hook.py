"""Hook entry point: record locally, output nothing, always leave approval alone."""
import json
from pathlib import Path
import sys

from live_events import record_hook


def main():
    try:
        payload = json.load(sys.stdin)
        source = {"codex": "Codex", "claude": "Claude"}.get(sys.argv[1])
        record_hook(Path(__file__).parent / ".board" / "live-events.sqlite3", source, payload)
    except Exception:
        # Observer failure must not interrupt an agent or decide its permissions.
        pass


if __name__ == "__main__":
    main()
