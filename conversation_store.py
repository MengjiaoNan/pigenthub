"""Read-only local transcript adapters; no agents or model calls are started."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import time

from list_sessions import read_titles
from native_links import conversation_link
from platform_support import agent_home

ACTIVE_WINDOW = 90
MESSAGE_LIMIT = 200


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def seconds(value):
    try:
        if isinstance(value, (float, int)):
            return value / 1000 if value > 100000000000 else value
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def text_blocks(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(b["text"] for b in content if isinstance(b, dict)
                     and b.get("type") in {"text", "input_text", "output_text"}
                     and isinstance(b.get("text"), str))


def request_text(text):
    for tag in ("environment_context", "recommended_plugins", "in-app-browser-context",
                "external_codex_apps_open_page", "system-reminder"):
        text = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", text, flags=re.S)
    if "## My request:" in text:
        text = text.split("## My request:", 1)[1]
    return re.sub(r"<image\b[^>]*>", "[图片]", text).strip()


def preview(text, limit=180):
    """Extract a short preview, without pretending it is an AI summary."""
    text = re.sub(r"```.*?```", " [code] ", text, flags=re.S)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"[Image: \1]", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = " ".join(text.split())
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def records(path):
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


class Transcript:
    def __init__(self, source, path, message_limit=MESSAGE_LIMIT):
        self.source, self.path = source, path
        self.message_limit = message_limit
        self.session_id = self.title = self.project = ""
        self.messages, self.events = [], []
        self.message_count = 0
        self.status = "unknown"
        self.reason = "本地记录没有可确认的运行状态"
        self.started_at = self.finished_at = self.observed_at = self.updated_at = None
        self.activity_at = None
        self.turn_id = None

    def observe(self, at):
        if at is not None:
            self.updated_at = max(self.updated_at or at, at)

    def event(self, text, at):
        if at is not None:
            self.activity_at = max(self.activity_at or at, at)
        self.events.append({"message": text, "timestamp": iso(at) if at else None})
        self.events = self.events[-60:]

    def message(self, role, text, at):
        if not text:
            return
        if at is not None:
            self.activity_at = max(self.activity_at or at, at)
        if self.messages and self.messages[-1]["role"] == role and self.messages[-1]["text"] == text:
            return
        if role == "user" and self.status in {"done", "cancelled", "failed"}:
            self.status, self.reason = "unknown", "已有新消息，尚未读到本轮开始事件"
            self.started_at = self.finished_at = None
        self.message_count += 1
        self.messages.append({"role": role, "text": text, "timestamp": iso(at) if at else None})
        if self.message_limit is not None:
            self.messages = self.messages[-self.message_limit:]
        if not self.title and role == "user":
            self.title = preview(text, 64)

    def mark(self, status, reason, at):
        self.status, self.reason, self.observed_at = status, reason, at
        if status == "running":
            self.finished_at = None
        elif status in {"done", "cancelled", "failed"}:
            self.finished_at = at
        self.event(reason, at)

    def card(self, now):
        status, reason = self.status, self.reason
        if status == "running" and (self.activity_at is None or now - self.activity_at > ACTIVE_WINDOW):
            if self.source == "Codex" and self.started_at is not None:
                # A quiet tool or approval wait does not end an explicit turn.
                reason = "本轮尚未结束，正在等待新的进展"
            else:
                status, reason = "unknown", "最后记录是运行中，但近期没有新事件；无法确认是否仍在工作"
        latest = self.messages[-1] if self.messages else None
        excerpt = latest["text"] if latest else ""
        kind = "任务摘录" if latest and latest["role"] == "user" else "回复摘录"
        if latest and latest["role"] == "assistant" and status == "running":
            kind = "最新进展摘录"
        return {
            "id": self.source.lower() + ":" + self.session_id,
            "session_id": self.session_id, "source": self.source,
            "title": self.title or "未命名对话", "project": self.project,
            "status": status, "status_reason": reason,
            "updated_at": iso(self.updated_at) if self.updated_at else None,
            "observed_at": iso(self.observed_at) if self.observed_at else None,
            "activity_at": iso(self.activity_at) if self.activity_at else None,
            "started_at": iso(self.started_at) if self.started_at else None,
            "finished_at": iso(self.finished_at) if self.finished_at else None,
            "message_count": self.message_count,
            "preview": preview(excerpt) or "尚无文字回复",
            "preview_kind": kind,
        }


def read_codex(path, message_limit=MESSAGE_LIMIT):
    result = Transcript("Codex", path, message_limit)
    event_messages = []
    for row in records(path):
        p = row.get("payload")
        if not isinstance(p, dict):
            continue
        at = seconds(row.get("timestamp"))
        result.observe(at)
        kind = p.get("type")
        if row.get("type") == "session_meta":
            source = p.get("source")
            if (isinstance(source, dict) and "subagent" in source) or p.get("thread_source") == "guardian_review":
                return None
            result.session_id, result.project = p.get("id", ""), p.get("cwd", "")
        elif row.get("type") == "compacted":
            # This record is written after compaction, never a start signal.
            result.event("上下文压缩已完成", at)
            if result.status == "running":
                result.reason = "上下文压缩已完成，继续处理本轮"
        elif row.get("type") == "response_item":
            if kind == "message" and p.get("role") in {"user", "assistant"}:
                role, text = p["role"], text_blocks(p.get("content"))
                result.message(role, request_text(text) if role == "user" else text, at)
            elif kind in {"function_call", "custom_tool_call"}:
                result.event("调用工具 · " + str(p.get("name", "工具")), at)
            elif kind in {"function_call_output", "custom_tool_call_output"}:
                result.event("工具执行结果已写入", at)
        elif row.get("type") == "event_msg":
            if kind == "task_started":
                result.turn_id = p.get("turn_id")
                result.started_at = seconds(p.get("started_at")) or at
                result.mark("running", "已读到本轮开始事件", at)
            elif kind in {"task_complete", "turn_aborted"}:
                if result.turn_id and p.get("turn_id") and result.turn_id != p["turn_id"]:
                    continue
                if kind == "task_complete":
                    if isinstance(p.get("last_agent_message"), str):
                        result.message("assistant", p["last_agent_message"], at)
                    result.mark("done", "已读到本轮完成事件", at)
                else:
                    result.mark("cancelled", "本轮已中止", at)
                result.started_at = seconds(p.get("started_at")) or result.started_at
                result.finished_at = seconds(p.get("completed_at")) or at
            elif kind == "user_message" and isinstance(p.get("message"), str):
                text = request_text(p["message"])
                if text:
                    event_messages.append(("user", text, at))
                    if result.status in {"done", "cancelled", "failed"}:
                        result.status, result.reason = "unknown", "已有新消息，等待本轮状态事件"
                        result.started_at = result.finished_at = None
            elif kind == "agent_message" and isinstance(p.get("message"), str):
                event_messages.append(("assistant", p["message"], at))
            elif kind == "context_compacted":
                result.event("上下文压缩已完成", at)
                if result.status == "running":
                    result.reason = "上下文压缩已完成，继续处理本轮"
    present_roles = {m["role"] for m in result.messages}
    missing = [m for m in event_messages if m[0] not in present_roles]
    if missing:
        # Backfill old event-only logs without changing the final lifecycle state.
        lifecycle = (result.status, result.reason, result.started_at, result.finished_at)
        for role, text, at in missing:
            result.message(role, text, at)
        result.messages.sort(key=lambda m: m["timestamp"] or "")
        result.status, result.reason, result.started_at, result.finished_at = lifecycle
    return result if isinstance(result.session_id, str) and result.session_id else None


def active_branch(rows):
    """UUIDs on the latest recorded branch, from its newest message to the start.

    A transcript can fork, e.g. when another process resumed the same session.
    This does not tell us which branch an already-open desktop window has loaded.
    Mixing branches would combine incompatible conversation histories.
    """
    by_id = {r["uuid"]: r for r in rows if isinstance(r.get("uuid"), str)}
    leaf = next((r for r in reversed(rows) if r.get("type") in {"user", "assistant"}
                 and not r.get("isSidechain") and isinstance(r.get("uuid"), str)), None)
    if leaf is None:
        return None
    chain, node = set(), leaf
    while node is not None and node["uuid"] not in chain:
        chain.add(node["uuid"])
        # A compaction boundary links to the earlier history through logicalParentUuid.
        node = by_id.get(node.get("parentUuid") or node.get("logicalParentUuid"))
    return chain


def read_claude(path, message_limit=MESSAGE_LIMIT):
    result = Transcript("Claude", path, message_limit)
    custom_title = ""
    rows = list(records(path))
    chain = active_branch(rows)
    for row in rows:
        if chain is not None and isinstance(row.get("uuid"), str) and row["uuid"] not in chain:
            continue
        if row.get("isSidechain"):
            continue
        at = seconds(row.get("timestamp"))
        result.observe(at)
        result.session_id = row.get("sessionId") or result.session_id
        result.project = row.get("relocatedCwd") or row.get("cwd") or result.project
        kind = row.get("type")
        if kind == "custom-title" and isinstance(row.get("customTitle"), str):
            custom_title = row["customTitle"]
        message = row.get("message")
        if kind not in {"user", "assistant"} or not isinstance(message, dict):
            continue
        content = message.get("content")
        text = text_blocks(content)
        blocks = content if isinstance(content, list) else []
        if kind == "user":
            if row.get("isMeta"):
                continue
            if "[Request interrupted by user" in text:
                result.mark("cancelled", "用户已中止本轮", at)
                continue
            if text:
                result.message("user", request_text(text), at)
                result.started_at, result.finished_at = at, None
                result.status, result.reason = "unknown", "已有用户消息，等待可确认的执行记录"
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    result.event("工具执行结果已写入", at)
        else:
            result.message("assistant", text, at)
            tools = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
            if tools:
                for block in tools:
                    result.event("调用工具 · " + str(block.get("name", "工具")), at)
                result.status, result.reason, result.observed_at = "running", "最近记录显示 Agent 正在调用工具", at
                result.finished_at = None
            elif message.get("stop_reason") == "end_turn":
                result.mark("done", "已读到 Claude 本轮回复结束标记", at)
            elif text:
                result.status, result.reason, result.observed_at = "running", "正在生成回复，尚未读到结束标记", at
                result.finished_at = None
    result.title = custom_title or result.title
    return result if isinstance(result.session_id, str) and result.session_id and result.messages else None


class ConversationStore:
    def __init__(self, codex_home=None, claude_home=None, summaries=None, live_events=None):
        self.codex_home = Path(codex_home or agent_home("Codex")).expanduser()
        self.claude_home = Path(claude_home or agent_home("Claude")).expanduser()
        self.lock = Lock()
        self.cache, self.sessions, self.warnings, self.sources = {}, {}, [], []
        self.full_cache = None
        self.last_scan, self.scanned_at = 0, None
        self.summaries = summaries
        self.live_events, self.live_records = live_events, {}

    def card(self, item, request=False, retry=False):
        card = item.card(time())
        if self.live_events:
            card = self.live_events.overlay(card, self.live_records.get(card["id"]))
        card["open_url"] = conversation_link(item.source, item.session_id)
        # Closed only when the app reported SessionEnd; otherwise it may still be open there.
        live = self.live_records.get(card["id"])
        card["app_open"] = None if not live else live.get("last_event") != "SessionEnd"
        card["summary_state"], card["summary"], card["summary_error"] = "short", None, None
        latest = item.messages[-1] if item.messages else None
        if self.summaries and latest and latest["role"] == "assistant":
            card.update(self.summaries.describe(latest["text"], eligible=card["status"] not in {"running", "needs_you"}, request=request, retry=retry))
        return card

    def scan(self, force=False):
        now = time()
        if not force and now - self.last_scan < 2:
            return
        self.live_records = self.live_events.snapshot() if self.live_events else {}
        warnings, paths, sources = [], [], []
        for source, folder, reader in (
            ("Codex", self.codex_home / "sessions", read_codex),
            ("Claude", self.claude_home / "projects", read_claude),
        ):
            count, available = 0, False
            try:
                available = folder.is_dir()
                if not available:
                    warnings.append(source + " 本地会话目录尚不存在")
                else:
                    for path in folder.rglob("*.jsonl"):
                        if source == "Claude" and ("subagents" in path.parts or path.name.startswith("agent-")):
                            continue
                        paths.append((path, reader))
                        count += 1
            except OSError:
                warnings.append(source + " 会话目录暂时无法读取")
            sources.append({"name": source, "file_count": count, "available": available})
        titles = read_titles(self.codex_home, warnings)
        current, sessions = {}, {}
        for path, reader in paths:
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                cached = self.cache.get(path)
                transcript = cached[1] if cached and cached[0] == signature else reader(path)
                current[path] = (signature, transcript)
                if transcript is None:
                    continue
                if transcript.source == "Codex":
                    title = titles.get(transcript.session_id, {}).get("thread_name")
                    if isinstance(title, str) and title.strip():
                        transcript.title = title
                key = transcript.source.lower() + ":" + transcript.session_id
                previous = sessions.get(key)
                if previous is None or (transcript.updated_at or 0) > (previous.updated_at or 0):
                    sessions[key] = transcript
            except (OSError, ValueError, TypeError, KeyError, OverflowError):
                warnings.append("有一份本地记录暂时无法解析：" + path.name)
        self.cache, self.sessions, self.warnings = current, sessions, warnings
        self.sources, self.last_scan, self.scanned_at = sources, now, iso(now)

    def snapshot(self):
        with self.lock:
            self.scan()
            items = sorted(self.sessions.values(), key=lambda item: item.updated_at or 0, reverse=True)
            cards = [self.card(item) for item in items]
            return {"conversations": cards, "sources": self.sources,
                    "warnings": self.warnings, "scanned_at": self.scanned_at,
                    "listeners": self.live_events.listeners(self.live_records) if self.live_events else [],
                    "refresh_seconds": 3}

    def detail(self, key, full=False):
        with self.lock:
            self.scan()
            item = self.sessions.get(key)
            if item is None:
                return None
            messages = item.messages
            if full and item.message_count > len(messages):
                stat = item.path.stat()
                signature = (key, stat.st_mtime_ns, stat.st_size)
                if self.full_cache is None or self.full_cache[0] != signature:
                    reader = read_codex if item.source == "Codex" else read_claude
                    transcript = reader(item.path, message_limit=None)
                    self.full_cache = (signature, transcript.messages if transcript else messages)
                messages = self.full_cache[1]
            events = item.events + self.live_records.get(key, {}).get("events", [])
            events.sort(key=lambda event: event.get("timestamp") or "")
            return {**self.card(item), "messages": messages, "events": events[-90:],
                    "record_path": str(item.path),
                    "messages_omitted": max(0, item.message_count - len(messages))}

    def progress(self, key):
        """A small, read-only view of this turn for an expanded board card."""
        with self.lock:
            self.scan()
            item = self.sessions.get(key)
            if item is None:
                return None
            card = self.card(item)
            events = item.events + self.live_records.get(key, {}).get("events", [])
            events.sort(key=lambda event: event.get("timestamp") or "")
            started = item.started_at
            if started is not None:
                events = [event for event in events if (seconds(event.get("timestamp")) or 0) >= started]
            updates = [message for message in item.messages if message["role"] == "assistant" and
                       (started is None or (seconds(message.get("timestamp")) or 0) >= started)]
            latest = updates[-1] if updates else None
            return {"id": key, "status": card["status"], "status_reason": card["status_reason"],
                    "updated_at": card["updated_at"], "events": events[-6:],
                    "latest_update": {"text": preview(latest["text"], 700),
                                      "timestamp": latest["timestamp"]} if latest else None}

    def workflow(self, key):
        """Every recorded step for this conversation, oldest first."""
        with self.lock:
            self.scan()
            item = self.sessions.get(key)
            if item is None:
                return None
            events = item.events + self.live_records.get(key, {}).get("events", [])
            events.sort(key=lambda event: event.get("timestamp") or "")
            return {"id": key, "events": events}

    def request_summary(self, key, reply_key, retry=False):
        with self.lock:
            self.scan()
            item = self.sessions.get(key)
            if item is None:
                return None
            latest = item.messages[-1] if item.messages else None
            if not self.summaries or not latest or latest["role"] != "assistant":
                raise ValueError("当前没有可生成摘要的回复")
            if self.summaries.key(latest["text"]) != reply_key:
                raise ValueError("回复已更新，请刷新后再选择生成摘要")
            if self.card(item)["status"] in {"running", "needs_you"}:
                raise ValueError("请等本轮结束后，再选择生成摘要")
            return self.card(item, request=True, retry=retry)
