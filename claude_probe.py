import json
import subprocess
from pathlib import Path
from platform_support import claude_command

print("正在连接 Claude Code，请稍等……")

try:
    process = subprocess.run(
        [
            *claude_command(),
            "-p", "请只回复：工作台连接成功",
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
        print("调用失败：")
        print(process.stdout)
        print(process.stderr)
    else:
        result = json.loads(process.stdout)
        if result.get("is_error"):
            print("Claude 返回错误：", result.get("result"))
        else:
            print("Claude 回复：", result.get("result"))
            print("对话 ID：", result.get("session_id"))

except subprocess.TimeoutExpired:
    print("等待超过 120 秒，本次测试已停止。")
except FileNotFoundError:
    print("找不到 Claude Code，请检查安装路径。")
except json.JSONDecodeError:
    print("返回内容不是预期的 JSON：")
    print(process.stdout)
