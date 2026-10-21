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

    emit("run_started", "Analyzing the task")
    time.sleep(2)


    request = {
        "id": str(uuid4()),
        "summary": "Allow the simulated test to continue?",
        "options": [
            {"id": "allow_once", "label": "Allow once"},
            {"id": "deny", "label": "Deny"},
        ],
    }

    emit("approval_requested", "Waiting for your permission", request)

    decision = ask_permission(request)

    if decision not in {"allow_once", "deny"}:
        raise ValueError("Unrecognized approval choice.")

    emit("approval_resolved", f"User selected: {decision}", request)

    if decision == "deny":
        emit("run_cancelled", "You denied the request. The demo was cancelled.")
        return

    emit("activity", "Simulating a test run")
    time.sleep(3)
    emit("run_completed", "Simulated test completed")


def print_event(event):
    print(json.dumps(event, ensure_ascii=False, indent=2))


def terminal_permission(request):
    print("\n" + request["summary"])

    while True:
        choice = input("Enter 1 to allow once, or 2 to deny: ").strip()

        if choice == "1":
            return "allow_once"
        if choice == "2":
            return "deny"

        print("Enter 1 or 2.")


if __name__ == "__main__":
    run_demo(print_event, terminal_permission)