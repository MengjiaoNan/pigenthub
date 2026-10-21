from pathlib import Path
from html import escape
import json

project_dir = Path(__file__).parent

data_path = project_dir / "conversations.json"
conversations = json.loads(data_path.read_text(encoding="utf-8"))

cards = []

for conversation in conversations:
    title = escape(conversation.get("title") or "未命名对话")
    project = escape(conversation.get("project") or "未记录项目")
    source = escape(conversation.get("source") or "未知来源")

    cards.append(f"""
        <article class="card">
            <span>{source}</span>
            <h2>{title}</h2>
            <p>{project}</p>
        </article>
    """)

page = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>我的 Agent 对话看板</title>
    <style>
        body {
            font-family: system-ui, sans-serif;
            background: #f5f6fa;
            color: #242938;
            padding: 24px;
        }
        main {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
        }
        .card {
            background: white;
            padding: 20px;
            border: 1px solid #e2e5ed;
            border-radius: 12px;
            overflow-wrap: anywhere;
        }
        .card span { color: #5368c4; font-size: 13px; }
        .card h2 { font-size: 18px; }
        .card p { color: #687080; font-size: 13px; }
    </style>
</head>
<body>
    <h1>我的 Agent 对话看板</h1>
    <input
        id="search"
        type="search"
        placeholder="搜索对话标题或项目"
        aria-label="搜索对话"
    >
    <main>
""" + "\n".join(cards) + """
    </main>
    <script>
        const searchInput = document.querySelector("#search");
        const cards = document.querySelectorAll(".card");

        searchInput.addEventListener("input", () => {
            const keyword = searchInput.value.trim().toLowerCase();

            for (const card of cards) {
                const content = card.textContent.toLowerCase();
                card.hidden = !content.includes(keyword);
            }
        });
    </script>
</body>
</html>
"""

output_path = project_dir / "index.html"
output_path.write_text(page, encoding="utf-8")

print("网页已生成：", output_path)