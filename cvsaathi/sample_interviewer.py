"""Scripted text interviewer used in sample mode, when no Gemini credentials are set.

It is not an AI. It asks a fixed list of questions in English, copies the student's
answers into the notebook through the same rules the voice model must pass, and
understands a few English design phrases. It exists so the whole app (notebook,
rules, templates, review, export) can be used and tested without a cloud account.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .design import apply_changes, parse_request
from .notebook import SINGLE_FIELDS, normalize

if TYPE_CHECKING:
    from .session import Session

QUESTIONS: list[tuple[str, str]] = [
    ("full_name", "What is your full name?"),
    ("spell:full_name", ""),
    ("phone", "What is your 10-digit mobile number?"),
    ("email", "Do you have an email address? Type it, or say no."),
    ("city", "Which town or city do you live in?"),
    ("spell:city", ""),
    ("trade", "Which ITI trade did you study? For example: Electrician, Fitter, Welder, COPA."),
    ("institute", "What is the full name of your ITI or institute?"),
    ("spell:institute", ""),
    ("passing_year", "In which year did you pass, or will you pass? For example: 2024."),
    ("skills", "Which skills do you have? Separate them with commas, for example: house wiring, motor rewinding."),
    ("tools", "Which tools, machines or equipment can you use? Separate with commas, for example: pipe wrench, drill machine, multimeter."),
    ("experience", "Did you do an apprenticeship or a job? Type: role, company, how long. For example: Apprentice Electrician, KPTCL, 1 year. Or say no."),
    ("spell:experience", ""),
    ("duties", "What did you do there? Separate with commas."),
    ("projects", "Any projects or practical training to add? Separate with commas, or say no."),
    ("languages", "Which languages can you speak? For example: Kannada, Hindi, English."),
]
NO_WORDS = {"no", "nahi", "nahin", "illa", "none", "nothing", "skip", "na", "nope"}
YES_WORDS = {"yes", "y", "yeah", "correct", "right", "ok", "okay", "haan", "houdu", "sari", "sahi"}
_PREFIX = re.compile(
    r"^(my name is|name is|i am|i'm|it is|it's|this is|i live in|i stay in|i am from|from|"
    r"i studied|i did|i passed in|passed in|in|my number is|my mobile number is|number is|my email is|email is)\s+",
    re.IGNORECASE,
)

WELCOME = (
    "Namaste! I'm CV-Saathi, in sample mode: a scripted helper, not the AI voice agent. "
    "I'll ask a few questions and build your CV from your answers. You can type 'go back' at any time."
)


def _clean_answer(text: str) -> str:
    value = text.strip().strip(".!")
    for _ in range(2):
        value = _PREFIX.sub("", value).strip()
    return value


def _title(value: str) -> str:
    return value.title() if value.islower() else value


def _split(text: str) -> list[str]:
    parts = re.split(r",|;|\n|\band\b", text)
    return [p.strip().strip(".") for p in parts if p.strip().strip(".")]


def _letters(value: str) -> str:
    return ", ".join("-".join(word.upper()) for word in value.split())


class SampleInterviewer:
    def __init__(self) -> None:
        self.index = 0
        self.experience_id = ""
        self.started = False

    @property
    def done(self) -> bool:
        return self.index >= len(QUESTIONS)

    def _applies(self, session: "Session", key: str) -> bool:
        nb = session.notebook
        if key.startswith("spell:"):
            target = key.split(":", 1)[1]
            fact = nb.get(self.experience_id) if target == "experience" else nb.single(target)
            return bool(fact and fact.status == "needs_spelling")
        if key == "duties":
            return bool(self.experience_id)
        return True

    def _question(self, session: "Session") -> str:
        while not self.done and not self._applies(session, QUESTIONS[self.index][0]):
            self.index += 1
        if self.done:
            session.step = "review" if session.step == "interview" else session.step
            blockers = session.notebook.export_blockers(include_review=False)
            if blockers:
                return "Some things are still missing: " + "; ".join(blockers) + ". Type 'go back' to fix them."
            return "Your notebook is complete. Please check your CV and the name spellings on the next screen."
        key, text = QUESTIONS[self.index]
        if key.startswith("spell:"):
            target = key.split(":", 1)[1]
            nb = session.notebook
            if target == "experience":
                value, label = nb.get(self.experience_id).extra["employer"], "the company name"
            else:
                value, label = nb.single(target).value, f"your {SINGLE_FIELDS[target]['label'].lower()}"
            return f"I have {label} as '{value}': {_letters(value)}. Is that right? Say yes, or type the correct spelling."
        return text

    def opening(self, session: "Session") -> str:
        self.started = True
        reply = WELCOME + " " + self._question(session)
        session.notebook.add_turn("agent", reply)
        return reply

    def respond(self, session: "Session", text: str) -> dict[str, Any]:
        nb = session.notebook
        nb.add_turn("student", text)
        low = normalize(text)
        if low in {"go back", "back", "previous"}:
            self.index = max(0, min(self.index, len(QUESTIONS)) - 1)
            while self.index > 0 and QUESTIONS[self.index][0].startswith("spell:"):
                self.index -= 1
            if session.step != "interview":
                session.step = "interview"
            reply = "Okay, let's go back. " + self._question(session)
        elif self.done or session.step != "interview":
            reply = self._design(session, text)
        else:
            problem = self._answer(session, QUESTIONS[self.index][0], text)
            if problem:
                reply = problem + " " + self._question(session)
            else:
                self.index += 1
                reply = self._question(session)
        nb.add_turn("agent", reply)
        return {"reply": reply}

    def _answer(self, session: "Session", key: str, text: str) -> str | None:
        """Save one answer. Returns a problem message, or None when the answer was used."""
        nb = session.notebook
        value = _clean_answer(text)
        is_no = normalize(text) in NO_WORDS
        if key.startswith("spell:"):
            target = key.split(":", 1)[1]
            fact = nb.get(self.experience_id) if target == "experience" else nb.single(target)
            current = fact.extra["employer"] if target == "experience" else fact.value
            if normalize(text) in YES_WORDS:
                result = nb.confirm_spelling(fact.id if target == "experience" else target, current, text)
            else:
                # The student typed the spelling themselves: that is their own edit.
                result = nb.student_edit(fact.id, value, "employer" if target == "experience" else "value")
            return None if result["ok"] else result["message"]
        if key == "email" and is_no:
            return None
        if key in {"experience", "projects", "tools"} and is_no:
            return None
        if is_no or normalize(text) in YES_WORDS:
            return "Please type your answer."
        if key in {"full_name", "city", "institute", "trade"}:
            value = _title(value)
        if key == "phone":
            value = re.sub(r"\D", "", normalize(text))[-10:]
        if key == "email":
            value = value.replace(" ", "").lower()
        if key in SINGLE_FIELDS:
            result = nb.save_field(key, value, text)
            return None if result["ok"] else result["message"]
        if key in {"skills", "tools", "projects", "languages", "duties"}:
            items = _split(value)
            if not items:
                return "Please type at least one."
            field = {"skills": "skill", "tools": "tool", "projects": "project", "languages": "language"}.get(key)
            problems = []
            for item in items:
                item = item[0].upper() + item[1:]
                result = nb.add_duty(self.experience_id, item, text) if key == "duties" else nb.save_field(field, item, text)
                if not result["ok"]:
                    problems.append(f"'{item}': {result['message']}")
            return " ".join(problems) or None
        if key == "experience":
            parts = [p.strip() for p in value.split(",") if p.strip()]
            if len(parts) < 2:
                return "Please type the role and the company, separated by a comma."
            role, employer, duration = _title(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""
            result = nb.add_experience(role, employer, duration, text)
            if not result["ok"]:
                return result["message"]
            self.experience_id = result["experience_id"]
            return None
        return None

    def _design(self, session: "Session", text: str) -> str:
        parsed = parse_request(text)
        if "changes" not in parsed:
            return parsed["message"]
        result = apply_changes(session.design, parsed["changes"], has_photo=False)
        if result["ok"]:
            session.design_revision += 1
            if session.step in {"interview", "template"}:
                session.step = "design"
        said = []
        if result["applied"]:
            said.append("Done: " + ", ".join(result["applied"]) + ".")
        said += result["refused"]
        return " ".join(said)
