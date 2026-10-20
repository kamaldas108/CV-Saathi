"""Draft the fuller CV with a stronger text model, in one pass over the whole interview.

The live voice model is good at conversation but drifts when it also writes many CV
lines through small tool calls. So after the interview, a text model (Gemini 3.8 Flash
by default) reads the transcript and the saved lines and proposes new ones. Every
proposal goes through CvNotebook.suggest_line, so the same rules apply, and each one
shows on the Check screen as Suggested until the student keeps it.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from pydantic import BaseModel, Field

from .notebook import CvNotebook

DRAFT_MODEL_ID = os.getenv("CVS_DRAFT_MODEL", "gemini-3.8-flash")
# Newer Gemini text models are served from the "global" location on Vertex AI.
DRAFT_LOCATION = os.getenv("CVS_DRAFT_LOCATION", "global")


class DraftLine(BaseModel):
    field: str = Field(description="One of: skill, tool, duty, project, summary")
    value: str = Field(description="The CV line in short, plain CV English")
    based_on: str = Field(description="The student's exact words this line grows from, copied from the transcript")
    experience_id: str = Field(default="", description="For a duty: the id of the job it belongs to")


class Draft(BaseModel):
    lines: list[DraftLine]


INSTRUCTIONS = """
You write the draft CV for an ITI/VTI student in India from their interview. The student
will see every line you write highlighted on screen and tap Keep or Remove, so propose
useful lines, but stay honest.

Return only NEW lines that are not already in the saved lines:
- skill: fuller versions of what they said, plus 2-4 typical skills for their trade.
  Aim for 6-8 skills in total. Start with an action word where it fits.
- tool: typical tools and equipment for their trade they are likely to use. Aim for
  4-6 tools in total. One tool per line.
- duty: for each job (use its experience_id), 3-4 lines in total that expand what
  they said, with their specifics (what work, for whom, how many if they said it).
- project: one line from a project or practical training they described, if any.
- summary: 2 short, plain lines from the facts (trade, training, experience, top
  skills), only if there is no summary yet. No puffery ("proven", "expert", "passionate").

Hard rules:
- Never add an employer, certificate, grade, date or number the student did not say.
- Keep their meaning: "fix" is "repaired", not "installed"; "maintain" is "maintained".
- Respect anything they said no to.
- based_on must be the student's words copied exactly from a Student line in the
  transcript (a short phrase is fine). For a typical trade skill or tool, use the words
  where they said their trade.
- Write everything in English, even if the student spoke Kannada or Hindi.
""".strip()


def build_prompt(nb: CvNotebook) -> str:
    transcript = "\n".join(
        f"{'Student' if t['speaker'] == 'student' else 'Agent'}: {t['text']}" for t in nb.transcript
    )
    saved = [
        {"id": f.id, "field": f.field, "value": f.value, **({"employer": f.extra.get("employer", "")} if f.field == "experience" else {})}
        for f in nb.facts
    ]
    return f"{INSTRUCTIONS}\n\nSAVED LINES:\n{json.dumps(saved, ensure_ascii=False)}\n\nTRANSCRIPT:\n{transcript}"


def call_model(prompt: str) -> Draft:
    from google import genai
    from google.genai import types

    # A stuck call once left "Write my CV" blocked; give up after 60 s so the student can retry.
    client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=DRAFT_LOCATION,
                          http_options=types.HttpOptions(timeout=60_000))
    response = client.models.generate_content(
        model=DRAFT_MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Draft),
    )
    return Draft.model_validate_json(response.text)


def draft_cv(nb: CvNotebook, model: Callable[[str], Draft] = call_model) -> dict[str, Any]:
    """Ask the model for new lines and add each through the suggestion rules."""
    draft = model(build_prompt(nb))
    added, rejected = 0, []
    for line in draft.lines:
        result = nb.suggest_line(line.field, line.value, line.based_on, line.experience_id)
        if result.get("ok") and result.get("fact_id"):
            added += 1
        elif not result.get("ok"):
            rejected.append({"line": line.value, "reason": result.get("message", "")})
    return {"ok": True, "added": added, "rejected": rejected,
            "message": f"Draft ready: {added} suggested line{'s' if added != 1 else ''} to check."}
