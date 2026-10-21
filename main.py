from pathlib import Path
import json
import re


def read_conversation(file_path):
    """读取一个对话文件，返回一张卡片的数据。"""

    user_question = ""

    with file_path.open("r", encoding="utf-8") as f:
        first_record = json.loads(f.readline())
        metadata = first_record.get("payload", {})
        source_info = metadata.get("source")

        if isinstance(source_info, dict) and "subagent" in source_info:
            return None
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            payload = record.get("payload", {})

            if record.get("type") == "response_item" and payload.get("role") == "user":
                text_parts = []

                for block in payload.get("content", []):
                    if block.get("type") == "input_text":
                        text_parts.append(block.get("text", ""))

                raw_text = "\n".join(text_parts)

                cleaned_text = raw_text

                context_tags = [
                    "environment_context",
                    "recommended_plugins",
                    "in-app-browser-context",
                    "external_codex_apps_open_page",
                ]

                for tag in context_tags:
                    cleaned_text = re.sub(
                        rf"<{tag}\b[^>]*>.*?</{tag}>",
                        "",
                        cleaned_text,
                        flags=re.DOTALL,
                    )

                if "## My request:" in cleaned_text:
                    cleaned_text = cleaned_text.split("## My request:", 1)[1]

                cleaned_text = cleaned_text.strip()

                if cleaned_text:
                    user_question = cleaned_text
                    break

    return {
        "source": "Codex",
        "id": metadata.get("id"),
        "title": user_question.replace("\n", " ")[:50] or "未命名对话",
        "project": metadata.get("cwd"),
    }


sessions_dir = Path.home() / ".codex" / "sessions"
session_files = list(sessions_dir.rglob("*.jsonl"))

saved_titles = {}
index_path = sessions_dir.parent / "session_index.jsonl"

if index_path.is_file():
    with index_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                index_record = json.loads(line)
            except json.JSONDecodeError:
                continue

            conversation_id = index_record.get("id")
            title = index_record.get("thread_name")

            if conversation_id and title:
                saved_titles[conversation_id] = title

conversations = []

for file_path in session_files:
    try:
        conversation = read_conversation(file_path)
    except (OSError, json.JSONDecodeError) as error:
        print("跳过文件：", file_path.name, "原因：", error)
        continue

    if conversation is None:
        continue
    conversation["title"] = saved_titles.get(conversation["id"]) or conversation["title"]

    conversations.append(conversation)

print("成功读取的对话数量：", len(conversations))
print("\n前 5 张卡片：")
print(json.dumps(conversations[:5], ensure_ascii=False, indent=2))
output_path = Path(__file__).parent / "conversations.json"

output_path.write_text(
    json.dumps(conversations, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("\n卡片已保存到：", output_path)