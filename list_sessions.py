"""第一步：只读扫描 Codex 本地对话，用 Python 3.9+ 即可运行。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class Conversation:
    """连接器统一输出的数据；以后网页可以直接使用这些字段。"""

    source: str
    conversation_id: str
    title: str
    project: str
    updated_at: str
    message_count: int


def clean_text(text: str) -> str:
    """把标题整理成一行，移除终端控制字符。"""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = " ".join(text.split())
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)


def user_request(text: str) -> str:
    """排除自动附加的环境信息，让第一条真实请求能作为备用标题。"""
    for tag in ("environment_context", "in-app-browser-context",
                "external_codex_apps_open_page"):
        text = re.sub(r"<" + tag + r"\b[^>]*>.*?</" + tag + r">", "", text,
                      flags=re.DOTALL)
        text = re.sub(r"<" + tag + r"\b[^>]*/>", "", text)
    text = re.sub(r"^\s*## My request:\s*", "", text)
    return clean_text(text)


def message_text(payload: dict) -> str:
    content = payload.get("content", [])
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"] for block in content
        if isinstance(block, dict)
        and block.get("type") in ("input_text", "output_text")
        and isinstance(block.get("text"), str)
    )


def timestamp(value: object, fallback: float) -> float:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (ValueError, OverflowError):
            pass
    return fallback


def read_titles(codex_home: Path, warnings: list[str]) -> dict[str, dict]:
    """索引中通常有用户设置的标题，优先使用它。"""
    titles = {}
    index = codex_home / "session_index.jsonl"
    if not index.exists():
        return titles
    try:
        with index.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    titles[row["id"]] = row
    except OSError:
        warnings.append("The title index could not be read. Using the first user request instead.")
    return titles


def read_session(path: Path, titles: dict[str, dict]) -> Optional[Conversation]:
    """逐行读取一份记录，不把整个大文件一次性装进内存。"""
    metadata = {}
    first_request = ""
    user_messages = assistant_messages = event_user_messages = 0
    updated = path.stat().st_mtime

    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                # 对话仍在写入时，最后一行可能尚未写完；先跳过。
                continue
            if not isinstance(row, dict):
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if row.get("type") == "session_meta":
                metadata = payload
            elif row.get("type") == "response_item" and payload.get("type") == "message":
                role = payload.get("role")
                if role == "user":
                    request = user_request(message_text(payload))
                    if request:
                        user_messages += 1
                        first_request = first_request or request
                elif role == "assistant":
                    assistant_messages += 1
            elif row.get("type") == "event_msg" and payload.get("type") == "user_message":
                # 兼容部分旧记录；同一消息有两种记录时不重复计数。
                text = payload.get("message", "")
                request = user_request(text) if isinstance(text, str) else ""
                if request:
                    event_user_messages += 1
                    first_request = first_request or request

    conversation_id = metadata.get("id")
    if not isinstance(conversation_id, str) or not conversation_id:
        return None
    index = titles.get(conversation_id, {})
    title = index.get("thread_name")
    title = clean_text(title) if isinstance(title, str) else ""
    project = metadata.get("cwd")
    updated = max(updated, timestamp(index.get("updated_at"), updated))
    return Conversation(
        source="Codex",
        conversation_id=conversation_id,
        title=title or first_request[:100] or "Untitled conversation",
        project=project if isinstance(project, str) else "",
        updated_at=datetime.fromtimestamp(updated, timezone.utc).isoformat(),
        message_count=(user_messages or event_user_messages) + assistant_messages,
    )


def scan_sessions(codex_home: Path) -> tuple[list[Conversation], list[str]]:
    """读取数据来源，返回统一的对话列表和可理解的诊断信息。"""
    warnings = []
    folder = codex_home / "sessions"
    if not folder.is_dir():
        return [], ["Codex conversation directory not found: " + str(folder)]
    titles = read_titles(codex_home, warnings)
    conversations = {}
    for path in folder.rglob("*.jsonl"):
        try:
            conversation = read_session(path, titles)
        except OSError:
            warnings.append("A record could not be read: " + path.name)
            continue
        if conversation is not None:
            previous = conversations.get(conversation.conversation_id)
            if previous is None or conversation.updated_at > previous.updated_at:
                conversations[conversation.conversation_id] = conversation
    return sorted(conversations.values(), key=lambda item: item.updated_at, reverse=True), warnings


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Enter an integer greater than 0.")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description="List local Codex conversations without modifying them")
    parser.add_argument("--limit", type=positive_integer, default=10, help="Number of conversations to show (default: 10)")
    parser.add_argument("--search", default="", help="Search by title or project path")
    parser.add_argument("--json", action="store_true", help="Output JSON for use by other tools")
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))),
                        help="Codex data directory (default: CODEX_HOME or ~/.codex)")
    args = parser.parse_args()
    conversations, warnings = scan_sessions(args.codex_home.expanduser())
    query = args.search.casefold()
    matched = [item for item in conversations
               if query in item.title.casefold() or query in item.project.casefold()]
    selected = matched[:args.limit]
    for warning in warnings:
        print("Note: " + warning, file=sys.stderr)
    if args.json:
        print(json.dumps({"total": len(conversations), "matched": len(matched),
                          "conversations": [asdict(item) for item in selected]},
                         ensure_ascii=False, indent=2))
        return
    print("Read {} Codex conversations; {} matched; showing {}.\n".format(
        len(conversations), len(matched), len(selected)))
    for number, item in enumerate(selected, 1):
        updated = datetime.fromisoformat(item.updated_at).astimezone().strftime("%Y-%m-%d %H:%M %Z")
        print("{}. {}".format(number, item.title[:100]))
        print("   Project: " + (clean_text(item.project) or "Not recorded"))
        print("   Updated: {} | Messages: {} | Source: {}".format(updated, item.message_count, item.source))
        print("   ID: " + clean_text(item.conversation_id) + "\n")
    if not selected:
        print("No matching conversations. Adjust the search term or check --codex-home.")


if __name__ == "__main__":
    main()
