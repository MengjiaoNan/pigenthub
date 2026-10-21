"""Local conversation board. Reads agent transcripts; acts only when you click.

Actions (answering a request, sending a message) are POSTs guarded so that
only this page, on this machine, can trigger them.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_runner import AgentRunner
from board_settings import WAIT_CHOICES, load_focus, load_settings, mark_offline, mark_online, save_focus, save_settings
from conversation_store import ConversationStore
from summaries import SummaryService
from live_events import LiveEventStore
from board_runtime import APP_ID, instance_id

ROOT = Path(__file__).parent
ACTION_HEADER = "x-pigenthub"
summaries = SummaryService(ROOT / ".board" / "summaries.sqlite3")
live_events = LiveEventStore(ROOT / ".board" / "live-events.sqlite3")
store = ConversationStore(summaries=summaries, live_events=live_events)
runner = AgentRunner()


@asynccontextmanager
async def lifespan(app):
    mark_online(ROOT)
    yield
    mark_offline(ROOT)
    summaries.close()


app = FastAPI(title="PigentHub", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


@app.middleware("http")
async def only_this_page_can_act(request: Request, call_next):
    # Other websites cannot send a custom header to this server without a CORS
    # preflight, which is never allowed; the Host check blocks DNS rebinding.
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    acting = request.method not in {"GET", "HEAD", "OPTIONS"}
    if host not in {"127.0.0.1", "localhost"} or (acting and request.headers.get(ACTION_HEADER) != "1"):
        return JSONResponse({"detail": "Only this board page can do that."}, status_code=403)
    return await call_next(request)


def with_send_state(card):
    card["send"] = runner.state(card["id"])
    return card


@app.get("/api/health")
def check_health():
    return {"status": "ok", "mode": "observer", "app": APP_ID,
            "instance_id": instance_id(ROOT), "pid": os.getpid(),
            "launch_id": os.environ.get("BOARD_LAUNCH_ID"), "launcher_protocol": 2}


@app.get("/api/conversations")
def get_conversations():
    snapshot = store.snapshot()
    snapshot["conversations"] = [with_send_state(card) for card in snapshot["conversations"]]
    snapshot["focus"] = load_focus(ROOT)
    snapshot["settings"] = {**load_settings(ROOT), "wait_choices": list(WAIT_CHOICES)}
    return snapshot


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, full: bool = False):
    conversation = store.detail(conversation_id, full=full)
    if conversation is None:
        raise HTTPException(404, "This conversation is no longer available in the local records.")
    conversation["outbox"] = live_events.outbox(conversation_id)
    return with_send_state(conversation)


@app.delete("/api/conversations/{conversation_id}/outbox/{message_id}")
def cancel_message(conversation_id: str, message_id: int):
    if not live_events.cancel(conversation_id, message_id):
        raise HTTPException(409, "That message was already delivered.")
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/progress")
def get_progress(conversation_id: str):
    progress = store.progress(conversation_id)
    if progress is None:
        raise HTTPException(404, "This conversation is no longer available locally")
    return progress


@app.get("/api/conversations/{conversation_id}/workflow")
def get_workflow(conversation_id: str):
    workflow = store.workflow(conversation_id)
    if workflow is None:
        raise HTTPException(404, "This conversation is no longer available in the local records.")
    return workflow


class Answer(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    action: Literal["allow", "deny", "reply", "stop"]
    message: str = Field(default="", max_length=4000)


@app.post("/api/conversations/{conversation_id}/respond")
def respond(conversation_id: str, answer: Answer):
    error = live_events.respond(conversation_id, answer.request_id, answer.action, answer.message)
    if error:
        raise HTTPException(409, error)
    return {"ok": True}


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@app.post("/api/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, message: NewMessage):
    if not message.text.strip():
        raise HTTPException(422, "Write a message first.")
    card = store.detail(conversation_id)
    if card is None:
        raise HTTPException(404, "This conversation is no longer available in the local records.")
    if card["status"] in {"running", "needs_you"}:
        # Hand off as hook context. This is not a desktop UI delivery acknowledgement.
        listener = next((item for item in live_events.listeners(live_events.snapshot())
                         if item["source"] == card["source"]), {})
        if not listener.get("delivery"):
            raise HTTPException(409, "Message hooks are not installed for this agent. Wait for the turn to finish or reply in the agent app.")
        return {"ok": True, "queued": True, "id": live_events.queue(conversation_id, message.text.strip())}
    try:
        runner.send(conversation_id, card["source"], card["session_id"], card["project"], message.text)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(409, str(error)) from error
    return {"ok": True}


class Focus(BaseModel):
    conversations: list[str] = Field(max_length=50)


@app.put("/api/focus")
def put_focus(focus: Focus):
    try:
        return {"conversations": save_focus(ROOT, focus.conversations)}
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


class Settings(BaseModel):
    approval_wait_seconds: int


@app.put("/api/settings")
def put_settings(settings: Settings):
    try:
        return save_settings(ROOT, settings.model_dump())
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


class SummaryRequest(BaseModel):
    reply_key: str = Field(min_length=64, max_length=64)
    retry: bool = False


@app.post("/api/conversations/{conversation_id}/summary")
def generate_summary(conversation_id: str, request: SummaryRequest):
    try:
        card = store.request_summary(conversation_id, request.reply_key, retry=request.retry)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if card is None:
        raise HTTPException(404, "This conversation is no longer available in the local records.")
    return card


@app.get("/")
def show_workbench():
    return FileResponse(
        ROOT / "workbench.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/favicon.svg")
def brand_icon():
    return FileResponse(ROOT / "assets" / "pigenthub.svg", media_type="image/svg+xml")
