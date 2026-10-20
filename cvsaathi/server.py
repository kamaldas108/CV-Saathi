"""FastAPI backend for CV-Saathi.

Run with:  python -m uvicorn cvsaathi.server:app --port 8000

Two modes:
- live: GOOGLE_CLOUD_PROJECT is set. The browser streams microphone audio over
  /ws/live and Gemini Live on Vertex AI interviews the student by voice.
- sample: no cloud project. A scripted text interviewer (not AI) stands in, so the
  notebook, rules, templates, review and export can be used and tested offline.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

from .design import ACCENTS, FONT_PAIRS, SECTION_TITLES, TEMPLATES, VAGUE_OPTIONS, apply_changes  # noqa: E402
from .live_tools import LIVE_MODEL_ID, STEPS, TOOL_NAMES, build_live_config, draft_not_ready, run_tool  # noqa: E402
from .render import CvTooLong, cv_text, pdf_to_png, render_pdf, safe_filename  # noqa: E402
from .session import Session  # noqa: E402
from .notebook import strip_markers  # noqa: E402
from .drafting import DRAFT_MODEL_ID, draft_cv  # noqa: E402

logger = logging.getLogger("cvsaathi")
# Tool-call logging prints the student's CV data to the server console. Local debugging only.
LOG_TOOLS = os.getenv("CVS_LOG_TOOLS", "") == "1"
tool_log = logging.getLogger("uvicorn.error")

SESSION_TTL = 2 * 60 * 60  # in-memory only for now; 7-day drafts (F11) come in the next pass
SHARE_TTL = 7 * 24 * 60 * 60
MAX_SESSIONS = 200
LIVE_MAX_SECONDS = int(os.getenv("CVS_LIVE_MAX_SECONDS", "600"))  # 10 minutes of conversation
LIVE_IDLE_SECONDS = int(os.getenv("CVS_LIVE_IDLE_SECONDS", "60"))
# The public link has no access code: cap simultaneous voice interviews so the cloud
# credit can't be spent faster than this many 10-minute sessions at a time.
MAX_LIVE = int(os.getenv("CVS_MAX_LIVE", "5"))
COOKIE = "cvs_owner"

sessions: dict[str, Session] = {}
shares: dict[str, dict[str, Any]] = {}
_genai_client = None

app = FastAPI(title="CV-Saathi")


def live_mode() -> bool:
    return bool(os.getenv("GOOGLE_CLOUD_PROJECT")) and os.getenv("CVS_SAMPLE_MODE", "") != "1"


def genai_client():
    """Gemini through Vertex AI, so usage draws on the Google Cloud credit."""
    global _genai_client
    if _genai_client is None:
        from google import genai

        _genai_client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    return _genai_client


# ----- sessions ------------------------------------------------------------------------------


def _cleanup() -> None:
    now = time.monotonic()
    for sid, session in list(sessions.items()):
        if now - session.updated_at > SESSION_TTL and session.live_socket is None:
            sessions.pop(sid, None)
    for token, share in list(shares.items()):
        if time.time() > share["expires"]:
            shares.pop(token, None)


def owned(session_id: str, owner: str | None) -> Session:
    session = sessions.get(session_id)
    if not session or not owner or not secrets.compare_digest(session.owner, owner):
        raise HTTPException(404, "This CV session was not found or has expired. Start a new one.")
    session.updated_at = time.monotonic()
    return session


def state(session: Session) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "mode": "live" if live_mode() else "sample",
        "live_model": LIVE_MODEL_ID if live_mode() else None,
        "step": session.step,
        "notebook": session.notebook.to_dict(),
        "transcript": session.notebook.transcript[-80:],
        "design": session.design.to_dict(),
        "design_revision": session.design_revision,
        "options": {
            "templates": TEMPLATES,
            "accents": {k: "#%02x%02x%02x" % v for k, v in ACCENTS.items()},
            "font_pairs": {k: v["label"] for k, v in FONT_PAIRS.items()},
            "sections": SECTION_TITLES,
            "vague_options": VAGUE_OPTIONS,
        },
    }


class StartRequest(BaseModel):
    consent: bool
    adult: bool


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class StepRequest(BaseModel):
    step: str


class DesignRequest(BaseModel):
    changes: dict[str, Any]


class EditRequest(BaseModel):
    value: str = Field(min_length=1, max_length=300)
    part: str = "value"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "mode": "live" if live_mode() else "sample", "live_model": LIVE_MODEL_ID, "tools": TOOL_NAMES}


@app.post("/api/sessions")
def create_session(body: StartRequest, request: Request, response: Response) -> dict[str, Any]:
    if not body.consent:
        raise HTTPException(400, "Consent is needed to start.")
    if not body.adult:
        raise HTTPException(403, "CV-Saathi is for students aged 18 or over in this pilot.")
    _cleanup()
    if len(sessions) >= MAX_SESSIONS:
        raise HTTPException(429, "Too many people are using CV-Saathi right now. Try again in a few minutes.")
    owner = request.cookies.get(COOKIE) or secrets.token_urlsafe(32)
    session = Session(owner=owner)
    sessions[session.id] = session
    if not live_mode():
        session.interviewer.opening(session)
    response.set_cookie(COOKIE, owner, httponly=True, samesite="strict", max_age=SESSION_TTL,
                        secure=request.url.scheme == "https")
    return state(session)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    return state(owned(session_id, request.cookies.get(COOKIE)))


@app.post("/api/sessions/{session_id}/message")
def message(session_id: str, body: MessageRequest, request: Request) -> dict[str, Any]:
    """Typed message in sample mode. In live mode, typed text travels over the WebSocket."""
    session = owned(session_id, request.cookies.get(COOKIE))
    if live_mode():
        raise HTTPException(409, "In live mode, send text through the voice connection.")
    if session.notebook.transcript and len(session.notebook.transcript) > 400:
        raise HTTPException(413, "This conversation is too long. Start over.")
    reply = session.interviewer.respond(session, body.text)
    return {"reply": reply["reply"], "state": state(session)}


@app.post("/api/sessions/{session_id}/step")
def set_step(session_id: str, body: StepRequest, request: Request) -> dict[str, Any]:
    session = owned(session_id, request.cookies.get(COOKIE))
    if body.step not in STEPS:
        raise HTTPException(400, "Unknown step.")
    if body.step == "export" and session.notebook.export_blockers():
        raise HTTPException(409, "; ".join(session.notebook.export_blockers()))
    session.step = body.step
    return state(session)


@app.post("/api/sessions/{session_id}/design")
def design(session_id: str, body: DesignRequest, request: Request) -> dict[str, Any]:
    session = owned(session_id, request.cookies.get(COOKIE))
    result = apply_changes(session.design, body.changes, has_photo=False)
    if result["ok"]:
        session.design_revision += 1
    return {"result": result, "state": state(session)}


@app.patch("/api/sessions/{session_id}/lines/{fact_id}")
def edit_line(session_id: str, fact_id: str, body: EditRequest, request: Request) -> dict[str, Any]:
    session = owned(session_id, request.cookies.get(COOKIE))
    result = session.notebook.student_edit(fact_id, body.value, body.part)
    if not result["ok"]:
        raise HTTPException(422, result["message"])
    return state(session)


def drafting_now(session: Session) -> bool:
    """A draft is really in progress (the flag alone once got stuck after a failure)."""
    background = session.draft_task is not None and not session.draft_task.done()
    return background or (session.drafting and session.draft_task is None)


@app.post("/api/sessions/{session_id}/draft")
def draft(session_id: str, request: Request) -> dict[str, Any]:
    """'Write my CV' button: run the drafting model now (live mode only; it needs Vertex AI)."""
    session = owned(session_id, request.cookies.get(COOKIE))
    if not live_mode():
        raise HTTPException(409, "Writing a draft needs the AI model. It isn't available in sample mode.")
    if drafting_now(session):
        raise HTTPException(409, "The draft is already being written.")
    session.drafting = True
    try:
        result = draft_cv(session.notebook)
    except Exception as exc:
        logger.exception("Drafting failed")
        raise HTTPException(502, "Writing the draft failed. Try again in a moment.") from exc
    finally:
        session.drafting = False
    session.step = "review"
    return {"message": result["message"], "state": state(session)}


@app.post("/api/sessions/{session_id}/lines/{fact_id}/keep")
def keep_line(session_id: str, fact_id: str, request: Request) -> dict[str, Any]:
    """The student tapped Keep on a suggested line, or 'Spelled right' on a name."""
    session = owned(session_id, request.cookies.get(COOKIE))
    result = session.notebook.keep_line(fact_id)
    if not result["ok"]:
        raise HTTPException(404, result["message"])
    return state(session)


@app.delete("/api/sessions/{session_id}/lines/{fact_id}")
def delete_line(session_id: str, fact_id: str, request: Request) -> dict[str, Any]:
    session = owned(session_id, request.cookies.get(COOKIE))
    result = session.notebook.remove(fact_id)
    if not result["ok"]:
        raise HTTPException(404, result["message"])
    return state(session)


@app.post("/api/sessions/{session_id}/approve")
def approve(session_id: str, request: Request) -> dict[str, Any]:
    session = owned(session_id, request.cookies.get(COOKIE))
    result = session.notebook.approve_review()
    if not result["ok"]:
        raise HTTPException(409, result["message"])
    session.step = "template"
    return state(session)


@app.post("/api/sessions/{session_id}/reset")
async def reset(session_id: str, request: Request) -> dict[str, Any]:
    session = owned(session_id, request.cookies.get(COOKIE))
    await session.close_live()
    for token, share in list(shares.items()):
        if share["session_id"] == session.id:
            shares.pop(token, None)
    session.reset()
    if not live_mode():
        session.interviewer.opening(session)
    return state(session)


def _render(session: Session, template: str | None = None) -> bytes:
    settings = session.design
    if template and template != settings.template:
        if template not in TEMPLATES:
            raise HTTPException(404, "Unknown template.")
        from .design import DesignSettings

        settings = DesignSettings(**{**settings.to_dict(), "template": template})
    try:
        return render_pdf(session.notebook, settings)
    except CvTooLong as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/sessions/{session_id}/preview.png")
def preview(session_id: str, request: Request, template: str | None = None, w: int = 720) -> Response:
    session = owned(session_id, request.cookies.get(COOKIE))
    png = pdf_to_png(_render(session, template), width_px=max(160, min(w, 1200)))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


def _export_gate(session: Session) -> None:
    blockers = session.notebook.export_blockers()
    if blockers:
        raise HTTPException(409, "Not ready to export: " + "; ".join(blockers))


@app.get("/api/sessions/{session_id}/cv.pdf")
def download_pdf(session_id: str, request: Request) -> Response:
    session = owned(session_id, request.cookies.get(COOKIE))
    _export_gate(session)
    name = session.notebook.single("full_name").value
    return Response(_render(session), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe_filename(name)}"', "Cache-Control": "no-store"})


@app.get("/api/sessions/{session_id}/cv.txt")
def download_text(session_id: str, request: Request) -> Response:
    session = owned(session_id, request.cookies.get(COOKIE))
    _export_gate(session)
    return Response(cv_text(session.notebook, session.design), media_type="text/plain; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/sessions/{session_id}/share")
def share(session_id: str, request: Request) -> dict[str, Any]:
    """A link that opens a snapshot of the PDF. Unguessable, unindexed, expires in 7 days."""
    session = owned(session_id, request.cookies.get(COOKIE))
    _export_gate(session)
    token = secrets.token_urlsafe(24)
    name = session.notebook.single("full_name").value
    shares[token] = {"pdf": _render(session), "filename": safe_filename(name), "session_id": session.id,
                     "expires": time.time() + SHARE_TTL}
    return {"url": str(request.base_url).rstrip("/") + f"/s/{token}", "expires_in_days": 7}


@app.get("/s/{token}")
def shared_pdf(token: str) -> Response:
    item = shares.get(token)
    if not item or time.time() > item["expires"]:
        shares.pop(token, None)
        raise HTTPException(404, "This link has expired.")
    return Response(item["pdf"], media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{item["filename"]}"',
        "X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    })


@app.get("/robots.txt")
def robots() -> Response:
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")


# ----- live voice ------------------------------------------------------------------------------


def _add_usage(session: Session, usage: Any) -> None:
    """Accumulate token counts by modality, for the cost log (spec: measure the pilot)."""
    if not usage:
        return
    totals = session.usage
    totals["messages"] = totals.get("messages", 0) + 1
    totals["total"] = totals.get("total", 0) + int(getattr(usage, "total_token_count", 0) or 0)
    for prefix, details in (("in", getattr(usage, "prompt_tokens_details", None)), ("out", getattr(usage, "response_tokens_details", None))):
        for item in details or []:
            key = f"{prefix}_{str(getattr(item, 'modality', 'unknown')).split('.')[-1].lower()}"
            totals[key] = totals.get(key, 0) + int(getattr(item, "token_count", 0) or 0)


def _log_usage(session: Session, started: float) -> None:
    if not session.usage:
        return
    entry = {"session": session.id, "model": LIVE_MODEL_ID, "seconds": round(time.monotonic() - started),
             "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **session.usage}
    # On Cloud Run local files vanish, so the line also goes to the log (token counts only, no CV content).
    tool_log.info("usage %s", json.dumps(entry))
    with contextlib.suppress(OSError):
        DATA_DIR.mkdir(exist_ok=True)
        with (DATA_DIR / "usage.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


@app.websocket("/ws/live")
async def live_voice(websocket: WebSocket) -> None:
    try:
        session = owned(websocket.query_params.get("session_id", ""), websocket.cookies.get(COOKIE))
    except HTTPException:
        await websocket.close(code=1008)
        return
    if session.live_socket is not None or not live_mode():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    if sum(1 for s in sessions.values() if s.live_socket is not None) >= MAX_LIVE:
        await websocket.send_json({"type": "error", "message": "CV-Saathi is busy right now. Please try again in a "
                                                               "few minutes, or type your answers."})
        await websocket.close(code=1013)
        return
    session.live_socket = websocket
    from google.genai import types

    nb = session.notebook
    send_lock = asyncio.Lock()
    pending = {"student": {"id": uuid.uuid4().hex, "text": ""}, "agent": {"id": uuid.uuid4().hex, "text": ""}}
    started = time.monotonic()
    activity = {"student": time.monotonic(), "agent": time.monotonic()}

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def send_state() -> None:
        await send({"type": "state", "state": state(session)})

    async def finalize(speaker: str) -> None:
        turn = pending[speaker]
        if strip_markers(turn["text"]):
            nb.add_turn(speaker, turn["text"], turn["id"])
            await send({"type": "transcript", "speaker": speaker, "text": strip_markers(turn["text"]), "id": turn["id"], "final": True})
        pending[speaker] = {"id": uuid.uuid4().hex, "text": ""}

    def start_drafting(live: Any) -> dict[str, Any]:
        """Run the drafting model in the background so the conversation doesn't freeze."""
        if drafting_now(session):
            return {"ok": True, "message": "The draft is already being written. Wait for the app's notice."}
        problem = draft_not_ready(nb)
        if problem:
            return {"ok": False, "message": problem}

        async def tell_browser(payload: dict[str, Any]) -> None:
            # The student may have paused the mic (connection closed): never let this fail the draft.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(send(payload), 5)

        async def run() -> None:
            # Everything is inside try/finally: once, a failed "drafting" message to a closed
            # connection killed this task before the try, and the flag stayed stuck on.
            session.drafting = True
            try:
                await tell_browser({"type": "drafting", "active": True})
                result = await asyncio.wait_for(asyncio.to_thread(draft_cv, nb), 90)
                if LOG_TOOLS:
                    tool_log.info("draft added=%s rejected=%s", result["added"],
                                  json.dumps(result["rejected"], ensure_ascii=False)[:600])
                session.step = "review"
                await tell_browser({"type": "state", "state": state(session)})
                notice = (f"(App notice, not the student: the draft CV is on screen with {result['added']} suggested "
                          "lines. Ask the student to check the highlighted lines and their name spellings, and tap "
                          "Keep or Remove.)")
            except Exception:
                logger.exception("Drafting failed")
                notice = "(App notice, not the student: writing the draft failed. Apologise briefly and ask them to tap 'Write my CV' to try again.)"
            finally:
                session.drafting = False
                await tell_browser({"type": "drafting", "active": False})
            with contextlib.suppress(Exception):
                await live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=notice)]), turn_complete=True)

        # Not in session.tasks: closing the voice connection must not throw the draft away.
        # Start over (session.reset) cancels it.
        session.draft_task = asyncio.create_task(run())
        return {"ok": True, "message": "Drafting started. Tell the student you are writing their CV and it takes about "
                                       "20 seconds. Do NOT say the draft is ready until the app's notice arrives; if "
                                       "the student speaks meanwhile, say it is still being written."}

    try:
        history = [
            types.Content(role="user" if t["speaker"] == "student" else "model", parts=[types.Part(text=t["text"])])
            for t in nb.transcript
        ]
        async with genai_client().aio.live.connect(model=LIVE_MODEL_ID, config=build_live_config(bool(history))) as live:
            if history:
                await live.send_client_content(turns=history, turn_complete=True)
            else:
                await live.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text="(The student has opened the app. Greet them and begin.)")]),
                    turn_complete=True,
                )
            await send({"type": "ready", "model": LIVE_MODEL_ID})
            await send_state()

            async def from_browser() -> None:
                while True:
                    raw = await websocket.receive_text()
                    if len(raw) > 400_000:
                        continue
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "audio":
                        data = base64.b64decode(message.get("data", ""), validate=True)
                        if data and len(data) % 2 == 0 and len(data) <= 128_000:
                            await live.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
                    elif kind == "text":
                        text = str(message.get("text", "")).strip()[:2000]
                        if text:
                            activity["student"] = time.monotonic()
                            turn_id = nb.add_turn("student", text)
                            await send({"type": "transcript", "speaker": "student", "text": text, "id": turn_id, "final": True})
                            await live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)
                    elif kind == "close":
                        return

            async def from_gemini() -> None:
                while True:
                    async for response in live.receive():
                        _add_usage(session, getattr(response, "usage_metadata", None))
                        if response.tool_call and response.tool_call.function_calls:
                            # The student's words must be in the transcript before the
                            # rules check a tool call's evidence against it.
                            await finalize("student")
                            replies = []
                            for call in response.tool_call.function_calls:
                                if call.name == "draft_cv":
                                    result = start_drafting(live)
                                else:
                                    result = run_tool(session, str(call.name or ""), dict(call.args or {}))
                                if LOG_TOOLS:  # local debugging only: contains CV data
                                    tool_log.info("tool %s %s -> ok=%s %s", call.name, json.dumps(dict(call.args or {}), ensure_ascii=False),
                                                  result.get("ok"), result.get("message", "")[:160])
                                await send({"type": "tool", "name": call.name, "ok": result.get("ok"), "message": result.get("message", "")})
                                replies.append(types.FunctionResponse(id=call.id, name=call.name, response=result))
                            await live.send_tool_response(function_responses=replies)
                            await send_state()
                        content = response.server_content
                        if not content:
                            continue
                        if content.interrupted:
                            await send({"type": "interrupted"})
                            await finalize("agent")
                        if content.input_transcription and content.input_transcription.text:
                            activity["student"] = time.monotonic()
                            pending["student"]["text"] += content.input_transcription.text
                            await send({"type": "transcript", "speaker": "student", "id": pending["student"]["id"], "text": strip_markers(pending["student"]["text"]), "final": False})
                        if content.output_transcription and content.output_transcription.text:
                            await finalize("student")
                            pending["agent"]["text"] += content.output_transcription.text
                            await send({"type": "transcript", "speaker": "agent", "id": pending["agent"]["id"], "text": strip_markers(pending["agent"]["text"]), "final": False})
                        if content.model_turn and not content.interrupted:
                            for part in content.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data and (part.inline_data.mime_type or "").startswith("audio/pcm"):
                                    activity["agent"] = time.monotonic()
                                    await send({"type": "audio", "data": base64.b64encode(part.inline_data.data).decode("ascii")})
                        if content.turn_complete:
                            await finalize("student")
                            await finalize("agent")
                            await send({"type": "turn_complete"})

            async def watchdog() -> str:
                while True:
                    await asyncio.sleep(2)
                    now = time.monotonic()
                    if now - started > LIVE_MAX_SECONDS:
                        return "The 10-minute voice session has ended. Your notebook is saved; tap the mic to continue."
                    if now - max(activity.values()) > LIVE_IDLE_SECONDS:
                        return "The voice session paused after a minute of silence. Tap the mic to continue."

            tasks = [asyncio.create_task(c) for c in (from_browser(), from_gemini(), watchdog())]
            session.tasks.update(tasks)
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception() is None and isinstance(task.result(), str):
                    await send({"type": "ended", "message": task.result()})
                elif task.exception() and not isinstance(task.exception(), WebSocketDisconnect):
                    raise task.exception()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Gemini Live session failed")
        with contextlib.suppress(Exception):
            await send({"type": "error", "message": "The voice connection failed. Check the server log; your notebook is kept."})
    finally:
        with contextlib.suppress(Exception):
            await finalize("student")
            await finalize("agent")
        for task in list(session.tasks):
            task.cancel()
        session.tasks.clear()
        session.live_socket = None
        _log_usage(session, started)
        with contextlib.suppress(Exception):
            await websocket.close()


# ----- static ----------------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/{name}")
def static_file(name: str) -> FileResponse:
    types_ = {"app.js": "text/javascript", "styles.css": "text/css", "audio-worklet.js": "text/javascript"}
    if name not in types_:
        raise HTTPException(404)
    return FileResponse(WEB_DIR / name, media_type=types_[name], headers={"Cache-Control": "no-store"})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
