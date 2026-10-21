from datetime import datetime, timezone
from uuid import uuid4
import time
import json


def run_demo(on_event, ask_permission):
    run_id = str(uuid4())

    def emit(event_type, message, request=None):
        on_event({
            "agent_id": "demo",
            "session_id": "demo-session",
            "run_id": run_id,
            "type": event_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request": request,
        })

    emit("run_started", "正在分析任务")
    time.sleep(2)


    request = {
        "id": str(uuid4()),
        "summary": "是否允许继续模拟测试？",
        "options": [
            {"id": "allow_once", "label": "允许本次"},
            {"id": "deny", "label": "拒绝"},
        ],
    }

    emit("approval_requested", "等待你处理权限请求", request)

    decision = ask_permission(request)

    if decision not in {"allow_once", "deny"}:
        raise ValueError("无法识别的审批选择")

    emit("approval_resolved", f"用户选择：{decision}", request)

    if decision == "deny":
        emit("run_cancelled", "你拒绝了请求，演示已取消")
        return

    emit("activity", "正在模拟运行测试")
    time.sleep(3)
    emit("run_completed", "模拟测试完成")


def print_event(event):
    print(json.dumps(event, ensure_ascii=False, indent=2))


def terminal_permission(request):
    print("\n" + request["summary"])

    while True:
        choice = input("输入 1 允许本次，输入 2 拒绝：").strip()

        if choice == "1":
            return "allow_once"
        if choice == "2":
            return "deny"

        print("请输入 1 或 2。")


if __name__ == "__main__":
    run_demo(print_event, terminal_permission)