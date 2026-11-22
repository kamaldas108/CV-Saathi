"""Run one CV All evaluation persona through a real live session and record everything.

Usage: python eval/run_case.py <persona_id> <run_label> <out_dir> [port]

The student is simulated: scripted lines from eval/personas.json are said verbatim and in
order; anything the script does not cover is improvised in character by a separate model
(Gemini 3.8 Flash) from the persona's fact sheet, and every improvised line is labelled so.
Turns are sent as transcribed speech (text) into the same WebSocket the browser uses.

After the draft appears the student: records the draft and an export attempt (expected to be
blocked), confirms names ("Spelled right"), removes every suggested line (so the exported CV
holds only lines from the student's own words), taps "Looks good", and exports. Design cases
then make their design requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

import httpx
import websockets
from google import genai
from google.genai import types
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
PERSONAS = json.loads((ROOT / "eval" / "personas.json").read_text(encoding="utf-8"))
QUIET = 4.0
MAX_STUDENT_TURNS = 26
SIM_MODEL = "gemini-3.8-flash"


class StudentTurn(BaseModel):
    use_script: bool
    text: str
    note: str


SIM_RULES = """You play an ITI student being interviewed by a CV assistant. Reply to the assistant's
latest message with ONE short answer, as the student would speak it.

- NEXT SCRIPTED LINE: if it is given and it fits now (it answers the question, the assistant
  asks an open question like "anything else?", or its condition is met), set use_script true;
  the exact line will be said. Scripted lines must be used as soon as they fit.
- Otherwise set use_script false and answer in character, ONLY from FACTS. If FACTS does not
  contain the answer, say you don't know or don't have it. Never invent anything.
- Speak in the student's language and style: {lang}. Keep it short, like speech.
- If the assistant reads a line or a spelling back and it matches FACTS, agree briefly.
- If the assistant asks you to check the screen or says the CV is being written, give a short
  acknowledgement.
"""


def persona(pid: str) -> dict:
    return next(p for p in PERSONAS["personas"] if p["id"] == pid)


def sim_client():
    return genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT", "cv-saathi"), location="global")


def simulate(client, p: dict, transcript: list[dict], pending: dict | None) -> StudentTurn:
    convo = "\n".join(f"{'Assistant' if t['speaker'] == 'agent' else 'Student'}: {t['text']}" for t in transcript[-14:])
    nxt = "none"
    if pending:
        nxt = json.dumps(pending, ensure_ascii=False)
    prompt = (SIM_RULES.format(lang=p["lang"]) + f"\nFACTS: {p['facts']}\n\nNEXT SCRIPTED LINE: {nxt}\n"
              f"(conditions: 'later' = only after at least three other answers since the previous scripted line; "
              f"'readback' = only when the assistant has just read a CV line back to you and asked if it is right)\n\n"
              f"CONVERSATION SO FAR:\n{convo}\n\nYour reply as JSON.")
    for wait in (3, 8, 15, None):
        try:
            r = client.models.generate_content(
                model=SIM_MODEL, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=StudentTurn,
                                                   temperature=0.3))
            return StudentTurn.model_validate_json(r.text)
        except Exception as exc:
            if wait is None or getattr(exc, "code", None) not in (429, 500, 503):
                raise
            time.sleep(wait)
    raise RuntimeError("unreachable")


async def main() -> None:
    pid, label, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 8002
    out_dir.mkdir(parents=True, exist_ok=True)
    p = persona(pid)
    sim = sim_client()
    started = time.time()
    log: list[dict] = []
    transcript: list[dict] = []
    record = lambda kind, **d: log.append({"t": round(time.time() - started, 1), "kind": kind, **d})

    script = [s if isinstance(s, dict) else {"text": s} for s in p.get("say", [])]
    interview_script = [s for s in script if s.get("when") != "after_draft"]
    after_draft = [s for s in script if s.get("when") == "after_draft"]
    since_script = 0
    result: dict = {"id": pid, "run": label, "set": p["set"], "family": p.get("family"), "lang": p["lang"]}

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=180) as http:
        r = await http.post("/api/sessions", json={"consent": True, "adult": True})
        sid, cookie = r.json()["session_id"], r.headers["set-cookie"].split(";")[0]
        H = {"Cookie": cookie}

        async def state():
            return (await http.get(f"/api/sessions/{sid}", headers=H)).json()

        ws = None
        completed = False

        async def connect():
            nonlocal ws, completed
            for _ in range(6):
                try:
                    ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws/live?session_id={sid}",
                                                  additional_headers=H, max_size=None, open_timeout=30)
                    completed = bool(transcript)  # on reconnect the agent waits for the student
                    record("note", text="connected" if not transcript else "reconnected (mic tapped again)")
                    return
                except Exception as exc:
                    record("note", text=f"connect failed: {type(exc).__name__}")
                    await asyncio.sleep(5)
            raise RuntimeError("could not connect")

        def handle(m):
            nonlocal completed
            if m["type"] == "transcript" and m["final"]:
                transcript.append({"speaker": m["speaker"], "text": m["text"]})
                record(m["speaker"], text=m["text"])
            elif m["type"] == "tool":
                record("tool", name=m["name"], ok=m["ok"], message=m["message"][:240])
            elif m["type"] in ("error", "ended"):
                record(m["type"], text=m["message"])
            elif m["type"] == "turn_complete":
                completed = True

        async def listen(seconds: float | None = None):
            """Read until the agent has finished and been quiet, or for a fixed time."""
            nonlocal completed
            end = time.time() + seconds if seconds else None
            while True:
                timeout = (end - time.time()) if end else (QUIET if completed else 90)
                if timeout <= 0:
                    return
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                except asyncio.TimeoutError:
                    if end or completed:
                        return
                    record("note", text="agent silent for 90 s")
                    return
                except websockets.exceptions.ConnectionClosed:
                    record("note", text="connection closed by server")
                    await connect()
                    return
                handle(m)

        async def say(text: str, kind: str):
            nonlocal completed
            record("student_sent", text=text, source=kind)
            try:
                await ws.send(json.dumps({"type": "text", "text": text}))
            except websockets.exceptions.ConnectionClosed:
                await connect()
                await ws.send(json.dumps({"type": "text", "text": text}))
            completed = False
            await listen()

        async def wait_for_draft(limit: float = 100):
            end = time.time() + limit
            while time.time() < end:
                st = await state()
                if st["step"] == "review" and any(f["status"] == "suggested" for f in st["notebook"]["facts"]):
                    return st
                await listen(5)
            return await state()

        await connect()
        await listen()
        # ----- interview ------------------------------------------------------------------
        turns = 0
        draft_state = None
        last_was_script = False
        claimed_at = None  # when the agent first said the CV is being written / is ready
        DRAFT_TALK = ("writing your cv", "draft cv", "your draft", "cv now", "सीवी बना", "सीवी तैयार", "ड्राफ्ट",
                      "ಸಿವಿ ಬರೆ", "ಸಿವಿ ತಯಾರ", "ಡ್ರಾಫ್ಟ್")
        while turns < MAX_STUDENT_TURNS:
            st = await state()
            if st["step"] == "review":
                draft_state = await wait_for_draft()
                break
            last_agent = next((t["text"].lower() for t in reversed(transcript) if t["speaker"] == "agent"), "")
            if claimed_at is None and any(k in last_agent for k in DRAFT_TALK):
                claimed_at = time.time()
            if claimed_at and time.time() - claimed_at > 60:
                # Agent said the CV is being written/ready but no draft appeared: a student taps "Write my CV".
                record("finding", text="agent claimed a draft but none existed after 60 s")
                result["phantom_draft_claim"] = True
                break
            pending = interview_script[0] if interview_script else None
            pending_for_sim = pending
            if pending and pending.get("when") == "later" and since_script < 3:
                pending_for_sim = None
            # Keep scripted exchanges together; never leave an unconditioned line unsaid for long.
            force = pending_for_sim is not None and not pending_for_sim.get("when") and (last_was_script or since_script >= 2)
            if force or pending_for_sim is None:
                turn = None if force else await asyncio.to_thread(simulate, sim, p, transcript, None)
            else:
                turn = await asyncio.to_thread(simulate, sim, p, transcript, pending_for_sim)
            if force or (turn and turn.use_script and pending_for_sim):
                interview_script.pop(0)
                since_script = 0
                last_was_script = True
                await say(pending_for_sim["text"], "script")
            else:
                since_script += 1
                last_was_script = False
                await say(turn.text, "improvised")
            turns += 1
        if draft_state is None:
            # The student taps "Write my CV" if the agent never drafted.
            res = await http.post(f"/api/sessions/{sid}/draft", headers=H)
            record("tap", text=f"Write my CV -> {res.status_code} {res.text[:160]}")
            draft_state = await state()
        result["unused_script"] = [s["text"] for s in interview_script]
        result["draft_facts"] = [{k: f[k] for k in ("id", "field", "value", "status", "source", "evidence", "extra")}
                                 for f in draft_state["notebook"]["facts"]]
        result["checklist"] = draft_state["notebook"]["checklist"]
        ex = await http.get(f"/api/sessions/{sid}/cv.pdf", headers=H)
        result["export_before_check"] = {"status": ex.status_code, "detail": ex.json().get("detail") if ex.status_code != 200 else "exported"}

        # ----- export pressure (D2) -------------------------------------------------------
        for s in after_draft:
            await say(s["text"], "script")
            ex = await http.get(f"/api/sessions/{sid}/cv.pdf", headers=H)
            result["export_under_pressure"] = {"status": ex.status_code, "detail": ex.json().get("detail") if ex.status_code != 200 else "exported"}

        # ----- check screen: confirm names, remove suggestions, approve, export ------------
        st = await state()
        for f in st["notebook"]["facts"]:
            if f["status"] == "needs_spelling":
                await http.post(f"/api/sessions/{sid}/lines/{f['id']}/keep", headers=H)
            elif f["status"] == "suggested":
                await http.delete(f"/api/sessions/{sid}/lines/{f['id']}", headers=H)
        ap = await http.post(f"/api/sessions/{sid}/approve", headers=H)
        record("tap", text=f"names confirmed, suggestions removed, Looks good -> {ap.status_code} {ap.text[:160] if ap.status_code != 200 else ''}")
        await listen(8)

        # ----- design requests (F6) ----------------------------------------------------------
        if p.get("flow") == "design":
            result["design_before"] = (await state())["design"]
            for s in p["design_say"]:
                await say(s["text"], "script")
                result.setdefault("design_after", []).append({"after": s["text"], "design": (await state())["design"]})

        final = await state()
        result["final_facts"] = [{k: f[k] for k in ("field", "value", "status", "source", "extra")} for f in final["notebook"]["facts"]]
        pdf = await http.get(f"/api/sessions/{sid}/cv.pdf", headers=H)
        txt = await http.get(f"/api/sessions/{sid}/cv.txt", headers=H)
        result["export_final"] = {"status": pdf.status_code}
        if pdf.status_code == 200:
            (out_dir / f"{pid}_{label}.pdf").write_bytes(pdf.content)
            result["cv_text"] = txt.text
        else:
            result["export_final"]["detail"] = pdf.json().get("detail")
        with contextlib.suppress(Exception):
            await ws.close()
        await http.post(f"/api/sessions/{sid}/reset", headers=H)

    result["seconds"] = round(time.time() - started)
    result["log"] = log
    (out_dir / f"{pid}_{label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{pid} {label}: {result['seconds']} s, export={result['export_final']['status']}, unused script={len(result['unused_script'])}")


asyncio.run(main())
