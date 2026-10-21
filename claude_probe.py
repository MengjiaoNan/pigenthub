import json
import subprocess
from pathlib import Path
from platform_support import claude_command

print("Connecting to Claude Code. Please wait...")

try:
    process = subprocess.run(
        [
            *claude_command(),
            "-p", "Reply with only: Workbench connection successful",
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
        print("Call failed:")
        print(process.stdout)
        print(process.stderr)
    else:
        result = json.loads(process.stdout)
        if result.get("is_error"):
            print("Claude returned an error:", result.get("result"))
        else:
            print("Claude reply:", result.get("result"))
            print("Conversation ID:", result.get("session_id"))

except subprocess.TimeoutExpired:
    print("Stopped this connection test after waiting for 120 seconds.")
except FileNotFoundError:
    print("Claude Code was not found. Check its installation path.")
except json.JSONDecodeError:
    print("The response was not valid JSON:")
    print(process.stdout)
