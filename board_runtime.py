"""Identity shared by the local server and its launcher."""
import hashlib
from pathlib import Path

APP_ID = "agent-conversation-board"
APP_NAME = "PigentHub"


def instance_id(root):
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]
