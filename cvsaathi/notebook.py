"""The CV notebook and the deterministic rules that guard it.

The voice model never writes the CV. It asks for changes through tools, and each
change goes through a CvNotebook method that accepts or rejects it. These rules
enforce the live notebook and checklist (F2), spelling confirmation (F4), no
invention (F5) and the no-sensitive-fields policy.

Every method returns a plain dict with "ok" and "message" so the result can be
handed straight back to the voice model as a tool response.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

SINGLE_FIELDS: dict[str, dict[str, Any]] = {
    "full_name": {"section": "contact", "label": "Full name", "spelling": True},
    "phone": {"section": "contact", "label": "Phone"},
    "email": {"section": "contact", "label": "Email"},
    "city": {"section": "contact", "label": "City", "spelling": True},
    "trade": {"section": "trade", "label": "Trade"},
    "qualification": {"section": "education", "label": "Course"},
    "institute": {"section": "education", "label": "Institute", "spelling": True},
    "passing_year": {"section": "education", "label": "Year of passing"},
    # Written from saved facts only, read to the student, and checked like any other line.
    "summary": {"section": "summary", "label": "Profile summary"},
}
LIST_FIELDS: dict[str, dict[str, Any]] = {
    "skill": {"section": "skills", "label": "Skill", "max": 25},
    "tool": {"section": "tools", "label": "Tool or equipment", "max": 15},
    "project": {"section": "projects", "label": "Project or practical training", "max": 5},
    "certification": {"section": "education", "label": "Certificate", "max": 5},
    "language": {"section": "languages", "label": "Language", "max": 6},
}
MAX_EXPERIENCE = 4
MAX_DUTIES = 6
MAX_VALUE_LENGTH = 200
MAX_SUMMARY_LENGTH = 350

# What a full CV usually has. Not required for export: these are prompts for the
# interviewer to keep asking, so the CV has substance (all of it from the student).
DEPTH_TARGETS = {"skill": 6, "tool": 4, "duty": 3, "project": 1}

REQUIRED = [
    ("full_name", "Full name"),
    ("contact", "Phone or email"),
    ("city", "City or town"),
    ("trade", "Trade"),
    ("institute", "Institute"),
    ("passing_year", "Year of passing"),
    ("skill", "At least one skill"),
]

# Words that mean "yes, that is right" in English, Hindi and Kannada, as typed or
# as the transcription model may write them.
AFFIRMATIONS = {
    "yes", "yeah", "yep", "correct", "right", "ok", "okay", "haan", "han", "ha", "haa",
    "ji", "sahi", "theek", "thik", "houdu", "howdu", "hodu", "sari", "hmm",
    "हाँ", "हां", "जी", "सही", "ठीक", "ಹೌದು", "ಸರಿ",
}
# Agreeing to a whole suggested list ("all of them", "both", "sab", "ella"). These count
# only for suggestions, and only when the reply has no "no"/"not" in it.
ALL_WORDS = {
    "all", "both", "everything", "sure", "definitely", "exactly", "sab", "sabhi", "ella", "yella", "ellaa",
    "सब", "सभी", "दोनों", "ಎಲ್ಲಾ", "ಎಲ್ಲ", "ಎರಡೂ",
}

NEGATIONS = {"not", "no", "never", "nahi", "nahin", "illa", "except", "nope", "dont", "didnt", "नहीं", "ಇಲ್ಲ"}

SENSITIVE_PATTERNS = [
    r"\bcaste\b", r"\breligion\b", r"\bhindu\b", r"\bmuslim\b", r"\bchristian\b", r"\bsikh\b",
    r"\bjain\b", r"\bbuddhist\b", r"\baadh?aa?r\b", r"\bmarried\b", r"\bunmarried\b",
    r"\bmarital\b", r"\bdate of birth\b", r"\bdob\b", r"\bborn on\b", r"\b(sc|st|obc)\b",
    r"\bgeneral category\b",
]

STOPWORDS = {
    "with", "from", "that", "this", "have", "basic", "knowledge", "good", "work", "works",
    "worked", "working", "skill", "skills", "experience", "using", "used", "able", "know",
    "known", "also", "into", "about", "years", "year", "month", "months", "level", "handling",
}

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
# Kannada and Devanagari digits map to ASCII so a transcript in either script still
# counts as evidence for "2023".
_SCRIPT_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯०१२३४५६७८९", "01234567890123456789")


def normalize(text: str) -> str:
    """Casefold, unify digits and number words, and drop punctuation."""
    text = unicodedata.normalize("NFKC", text or "").translate(_SCRIPT_DIGITS).casefold()
    # Keep "@", "." and "+" only inside tokens such as emails, so "Ravi." matches "Ravi".
    text = re.sub(r"[^\w@.+]+", " ", text)
    text = re.sub(r"(?<!\w)[@.+]+|[@.+]+(?!\w)", " ", text)
    words = [_DIGIT_WORDS.get(word, word) for word in text.split()]
    # "double five" -> "5 5"
    out: list[str] = []
    for i, word in enumerate(words):
        if word == "double" and i + 1 < len(words) and words[i + 1].isdigit():
            out.append(words[i + 1])
            continue
        out.append(word)
    return " ".join(out).strip()


def digits_of(text: str) -> str:
    return re.sub(r"\D", "", normalize(text))


# Transcription tags ("<no speech>", "{pause}", "[noise]") and markup the voice model
# sometimes leaks into its words ("### Draft CV Creation <Step title=... />"). Students
# never speak in markup, so any <...> tag or ### heading is removed.
_MARKERS = re.compile(
    r"<[^<>]{0,300}>"                     # any tag, with or without attributes
    r"|\{\s*[a-z_ ]{1,24}\s*\}"            # {pause}
    r"|\[\s*(?:noise|pause|silence|inaudible|music|laughter)\s*\]"
    r"|#{2,}[^<\n]*",                     # markdown headings
    re.IGNORECASE,
)


def strip_markers(text: str) -> str:
    """Remove transcription tags such as "<no speech>", "{pause}" or "[noise]"."""
    return re.sub(r"\s{2,}", " ", _MARKERS.sub(" ", text or "")).strip()


def name_in(name: str, text: str) -> bool:
    """Whether a name (employer, institute) appears in the text, allowing plural and
    inflection differences: "Urban Company" is in "working in urban companies".
    Spelled-out letters ("K-P-T-C-L") also count."""
    if letters_of(name) and letters_of(name) in letters_of(text):
        return True
    said = re.findall(r"[a-z0-9]+", normalize(text))
    words = re.findall(r"[a-z0-9]+", normalize(name))

    def same(w: str, e: str) -> bool:
        if w == e:
            return True
        if len(w) < 4 or len(e) < 4:
            return False
        common = len(os.path.commonprefix([w, e]))
        return common >= 4 and common >= min(len(w), len(e)) - 2

    return bool(words) and all(any(same(w, e) for e in said) for w in words)


def number_said(number: str, text: str) -> bool:
    """Whether this number appears in the text as a whole number.

    "50" is not "said" just because it occurs inside the phone number 9845012345. Long
    numbers (phones) may be spoken digit by digit, so for those the digits are joined.
    """
    if number in re.findall(r"\d+", normalize(text)):
        return True
    return len(number) >= 6 and number in digits_of(text)


def letters_of(text: str) -> str:
    return re.sub(r"[^a-z]", "", normalize(text))


def spoken_letters(text: str) -> str:
    """Only the letters given one at a time: "R-A-M-A, rest is okay" -> "rama"."""
    tokens = re.split(r"[^a-z]+", unicodedata.normalize("NFKC", text or "").casefold())
    return "".join(t for t in tokens if len(t) == 1)


def _mostly_ascii(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.9


def _content_stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z]+", normalize(text)) if len(w) >= 4 and w not in STOPWORDS}


def unspell(value: str) -> str | None:
    """Turn a letter-by-letter spelling into the written name.

    "R-A-V-I K-U-M-A-R" -> "Ravi Kumar". Spaced single letters ("R A V I K U M A R")
    give no word breaks, so they return None. Anything else is returned unchanged.
    """
    tokens = [t for t in re.split(r"[\s,]+", value.strip()) if t]
    if not tokens:
        return value
    letter_words = [re.fullmatch(r"(?:[A-Za-z][-.]){1,}[A-Za-z]\.?", t) for t in tokens]
    if all(letter_words):
        return " ".join(re.sub(r"[-.]", "", t).capitalize() for t in tokens)
    if len(tokens) > 2 and all(len(t.strip(".-")) == 1 for t in tokens):
        return None
    return value


def sensitive_reason(value: str) -> str | None:
    lowered = normalize(value)
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, lowered):
            return "This looks like personal information (caste, religion, Aadhaar, marital status or date of birth). It is kept off the CV."
    if len(digits_of(value)) == 12:
        return "A 12-digit number looks like an Aadhaar number. It is kept off the CV."
    return None


@dataclass
class Fact:
    id: str
    field: str
    section: str
    value: str
    evidence: str
    source: str = "interview"  # "interview" or "student_edit"
    status: str = "draft"  # "draft", "needs_spelling" or "confirmed"
    parent: str = ""  # a duty's experience id
    extra: dict[str, str] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **extra}


def _no(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "message": message, **extra}


class CvNotebook:
    def __init__(self) -> None:
        self.facts: list[Fact] = []
        self.transcript: list[dict[str, str]] = []
        self.reviewed = False
        self.revision = 0
        self.spelling_failures: dict[str, int] = {}
        self.no_experience = ""
        self.experience_attempts = 0  # rejected add_experience calls: don't block drafting forever  # the student's words saying they have no job or apprenticeship

    # ----- transcript -----------------------------------------------------------------

    def add_turn(self, speaker: str, text: str, turn_id: str | None = None) -> str:
        turn_id = turn_id or uuid.uuid4().hex
        if any(t["id"] == turn_id for t in self.transcript):
            return turn_id
        text = strip_markers(text)
        if not text:
            return turn_id
        self.transcript.append({"id": turn_id, "speaker": speaker, "text": text[:4000]})
        return turn_id

    def student_said(self, evidence: str) -> bool:
        """True when every quote in the evidence appears in something the student said or typed.

        Facts often come from several answers ("Urban Company" ... "I was plumber" ...
        "last one year"), so evidence may hold several quotes separated by "|".
        """
        quotes = [normalize(q) for q in str(evidence or "").split("|")]
        quotes = [q for q in quotes if q]
        if not quotes:
            return False
        said = [normalize(t["text"]) for t in self.transcript if t["speaker"] == "student"]
        return all(any(q in text for text in said) for q in quotes)

    def _student_turn_index(self, evidence: str) -> int | None:
        """Index of the latest student turn that contains the evidence's last quote."""
        quote = normalize(str(evidence or "").split("|")[-1])
        for i in range(len(self.transcript) - 1, -1, -1):
            turn = self.transcript[i]
            if turn["speaker"] == "student" and quote and quote in normalize(turn["text"]):
                return i
        return None

    def _agent_turn_before(self, evidence: str) -> str:
        """The agent's words just before the student turn that contains the (last) quote."""
        index = self._student_turn_index(evidence)
        if index is None:
            return ""
        earlier = [t["text"] for t in self.transcript[:index] if t["speaker"] == "agent"]
        return earlier[-1] if earlier else ""

    # ----- lookups --------------------------------------------------------------------

    def get(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fact_id), None)

    def single(self, name: str) -> Fact | None:
        return next((f for f in self.facts if f.field == name), None)

    def values(self, name: str) -> list[Fact]:
        return [f for f in self.facts if f.field == name]

    def duties(self, experience_id: str) -> list[Fact]:
        return [f for f in self.facts if f.field == "duty" and f.parent == experience_id]

    # ----- rules ----------------------------------------------------------------------

    def _check_value(self, name: str, value: str) -> str | None:
        if not value:
            return "The value is empty."
        limit = MAX_SUMMARY_LENGTH if name == "summary" else MAX_VALUE_LENGTH
        if len(value) > limit:
            return f"Keep this under {limit} characters."
        reason = sensitive_reason(value)
        if reason and name != "phone":
            return reason
        if name == "phone":
            digits = digits_of(value)
            if digits.startswith("91") and len(digits) == 12:
                digits = digits[2:]
            if len(digits) != 10:
                return "An Indian mobile number has 10 digits. Ask the student to say or type it again."
        if name == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", value.lower()):
            return "That is not a complete email address. Ask the student to spell it."
        if name == "passing_year":
            if not re.fullmatch(r"\d{4}", value) or not 1980 <= int(value) <= date.today().year + 3:
                return "The year of passing must be a 4-digit year such as 2024."
        return None

    def _check_evidence(self, name: str, value: str, evidence: str) -> str | None:
        """The no-invention rule (F5). Everything on the CV traces to the student's words."""
        if not evidence.strip():
            return "Give the student's own words as evidence."
        if not self.student_said(evidence):
            return ("The evidence is not in anything the student said or typed. Copy the student's words exactly; "
                    "if the fact came from several answers, give each quote separated by ' | '. "
                    "Do not ask the student to repeat themselves.")
        offered = self.offer_accepted(evidence)
        support = f"{evidence} {offered}"
        for run in re.findall(r"\d+", normalize(value)):
            if not number_said(run, support):
                return f"The number {run} is not in the student's words. Ask the student to say it, then save it."
        if name == "email":
            spoken = normalize(evidence).replace(" at the rate ", "@").replace(" at ", "@").replace(" dot ", ".")
            if value.lower().replace(" ", "") not in spoken.replace(" ", ""):
                return "The email address does not match what the student said. Ask them to spell it."
        if name in LIST_FIELDS or name in {"duty", "experience", "qualification", "trade", "summary"}:
            stems = _content_stems(value)
            if not stems:
                return None
            if offered and _mostly_ascii(offered):
                # The student said yes to a line the agent suggested. Every content word
                # must be in what the agent said or what the student said, and nothing
                # the student ruled out ("yes, but not drainage") may be saved.
                if stems & self._ruled_out(evidence):
                    return "The student said no to part of this. Save only what they agreed to."
                if stems <= _content_stems(support):
                    return None
                if not (stems & _content_stems(evidence)):
                    return ("This line is not what you suggested to the student. Read the exact line to them and "
                            "save it only after they agree.")
                return None
            # Rephrasing is allowed, adding is not. With English evidence, the CV line
            # must share at least one content word with what the student said.
            if _mostly_ascii(evidence) and not (stems & _content_stems(evidence)):
                return ("This line adds words the student never said. Rephrase only what they said, or suggest "
                        "it to them and save it if they agree.")
        return None

    def offer_accepted(self, evidence: str) -> str:
        """If the evidence is the student saying yes, the agent turn they were agreeing to."""
        words = set(normalize(evidence).split())
        index = self._student_turn_index(evidence)
        turn_words = set(normalize(self.transcript[index]["text"]).split()) if index is not None else words
        agreed = bool(words & AFFIRMATIONS) or (bool(words & ALL_WORDS) and not turn_words & NEGATIONS)
        return self._agent_turn_before(evidence) if agreed else ""

    def _ruled_out(self, evidence: str) -> set[str]:
        """Content stems the student put after a "not"/"no" in the turn they said yes in."""
        index = self._student_turn_index(evidence)
        if index is None:
            return set()
        words = normalize(self.transcript[index]["text"]).split()
        for i, word in enumerate(words):
            if word in NEGATIONS:
                return _content_stems(" ".join(words[i + 1:]))
        return set()

    def _changed(self) -> None:
        self.revision += 1
        self.reviewed = False

    def _replace_everywhere(self, old: str, new: str, skip: Fact | None = None) -> None:
        """A corrected spelling replaces the old one in every line of the CV (F4)."""
        if not old or old.casefold() == new.casefold():
            return
        pattern = re.compile(re.escape(old), re.IGNORECASE)
        for fact in self.facts:
            if fact is skip:
                continue
            fact.value = pattern.sub(new, fact.value)
            fact.extra = {k: pattern.sub(new, v) for k, v in fact.extra.items()}

    # ----- writes from the interview ----------------------------------------------------

    def save_field(self, name: str, value: str, evidence: str) -> dict[str, Any]:
        value = " ".join(str(value or "").split())
        if name not in SINGLE_FIELDS and name not in LIST_FIELDS:
            return _no(f"'{name}' is not a CV field. Allowed: {', '.join([*SINGLE_FIELDS, *LIST_FIELDS])}. Use add_experience for jobs and apprenticeships.")
        problem = self._check_value(name, value) or self._check_evidence(name, value, evidence)
        if problem:
            return _no(problem)
        if name in SINGLE_FIELDS:
            spec = SINGLE_FIELDS[name]
            status = "needs_spelling" if spec.get("spelling") else "draft"
            existing = self.single(name)
            if existing:
                old = existing.value
                existing.value, existing.evidence, existing.status, existing.source = value, evidence, status, "interview"
                existing.updated_at = time.time()
                if spec.get("spelling"):
                    self._replace_everywhere(old, value, skip=existing)
                fact = existing
            else:
                fact = Fact(uuid.uuid4().hex[:10], name, spec["section"], value, evidence, status=status)
                self.facts.append(fact)
        else:
            spec = LIST_FIELDS[name]
            same = [f for f in self.values(name) if f.value.casefold() == value.casefold()]
            if same:
                return _ok("Already in the notebook.", fact_id=same[0].id)
            if len(self.values(name)) >= spec["max"]:
                return _no(f"The CV already has {spec['max']} entries for {spec['label'].lower()}. Ask which to keep.")
            fact = Fact(uuid.uuid4().hex[:10], name, spec["section"], value, evidence)
            self.facts.append(fact)
        self._changed()
        message = "Saved."
        if fact.status == "needs_spelling":
            message = "Saved. Read the spelling back letter by letter and call confirm_spelling once the student agrees."
        return _ok(message, fact_id=fact.id, checklist=self.checklist())

    def add_experience(self, role: str, employer: str, duration: str, evidence: str) -> dict[str, Any]:
        role, employer, duration = (" ".join(str(x or "").split()) for x in (role, employer, duration))
        if len(self.values("experience")) >= MAX_EXPERIENCE:
            return _no(f"The CV already lists {MAX_EXPERIENCE} jobs or apprenticeships.")
        for part in (role, employer):
            problem = self._check_value("experience", part)
            if problem:
                return _no(problem)
        # Evidence must be the student's, and any number in the duration must be theirs.
        problem = self._check_evidence("duration", duration, evidence)
        support = f"{evidence} {self.offer_accepted(evidence)}"
        if not problem and _mostly_ascii(support) and _content_stems(role):
            # The role often comes from the trade they gave earlier ("Electrician").
            trade = self.single("trade")
            known = _content_stems(support) | (_content_stems(trade.value) if trade else set())
            if not _content_stems(role) & known:
                problem = "The role adds words the student never said. Use their words or their trade."
        if not problem and _mostly_ascii(support) and not name_in(employer, support):
            problem = "The employer's name is not in the student's words. Ask the student for it."
        if not problem and duration:
            problem = self._check_value("experience", duration)
        if problem:
            self.experience_attempts += 1
            return _no(problem)
        fact = Fact(uuid.uuid4().hex[:10], "experience", "experience", role, evidence,
                    status="needs_spelling", extra={"employer": employer, "duration": duration})
        self.facts.append(fact)
        self._changed()
        return _ok("Saved. Confirm the employer's spelling with confirm_spelling, target = this experience_id.",
                   experience_id=fact.id, checklist=self.checklist())

    def mark_no_experience(self, evidence: str) -> dict[str, Any]:
        """Record that the student said they have no job or apprenticeship (so drafting can go ahead)."""
        if not self.student_said(evidence):
            return _no("The evidence is not in anything the student said.")
        words = set(normalize(evidence).split())
        if not words & (NEGATIONS | {"fresher", "none", "nothing"}):
            return _no("The evidence must be the student saying they have no job or apprenticeship.")
        if self.values("experience"):
            return _no("A job or apprenticeship is already saved.")
        self.no_experience = evidence
        return _ok("Noted: no job or apprenticeship yet. Ask about practical training, OJT or projects instead.")

    def add_duty(self, experience_id: str, text: str, evidence: str) -> dict[str, Any]:
        text = " ".join(str(text or "").split())
        parent = self.get(experience_id)
        if not parent or parent.field != "experience":
            return _no("Unknown experience_id. Call add_experience first.")
        if len(self.duties(experience_id)) >= MAX_DUTIES:
            return _no(f"Keep at most {MAX_DUTIES} duties per job.")
        problem = self._check_value("duty", text) or self._check_evidence("duty", text, evidence)
        if problem:
            return _no(problem)
        fact = Fact(uuid.uuid4().hex[:10], "duty", "experience", text, evidence, parent=experience_id)
        self.facts.append(fact)
        self._changed()
        return _ok("Saved.", fact_id=fact.id)

    def confirm_spelling(self, target: str, spelled: str, evidence: str) -> dict[str, Any]:
        """Mark a name final once the student has spelled it or agreed to the read-back."""
        spelled = unspell(" ".join(str(spelled or "").split()))
        if spelled is None:
            return _no("Pass the name written normally, for example 'Ravi Kumar', not as separate letters.")
        fact = self.single(target) if target in SINGLE_FIELDS else self.get(target)
        if not fact or not (SINGLE_FIELDS.get(fact.field, {}).get("spelling") or fact.field == "experience"):
            return _no("Target must be full_name, city, institute, or an experience_id.")
        if not self.student_said(evidence):
            return _no("The evidence is not in anything the student said or typed.")
        current = fact.extra["employer"] if fact.field == "experience" else fact.value
        if letters_of(spelled) == letters_of(current):
            spelled = current  # same letters: keep the saved form, e.g. "KPTCL" not "Kptcl"
        # Saying the name normally ("My name is Ram Kumar") is not spelling it. Spelled
        # out means separate letters in the student's words: "R-A-M K-U-M-A-R".
        spelled_out = bool(letters_of(spelled)) and letters_of(spelled) in spoken_letters(evidence)
        said_yes = bool(set(normalize(evidence).split()) & AFFIRMATIONS)
        # A yes counts for the spelling that was saved, or for the exact spelling the
        # agent read back in the turn the student was answering.
        agreed = said_yes and (spelled.casefold() == current.casefold()
                               or letters_of(spelled) in letters_of(self._agent_turn_before(evidence)))
        if not (spelled_out or agreed):
            failures = self.spelling_failures.get(fact.id, 0) + 1
            self.spelling_failures[fact.id] = failures
            if failures >= 2:
                return _no("Stop asking about this spelling now. Tell the student it stays as it is for now and they can "
                           "fix it by tapping it on the Check screen. Move on to the next question.")
            return _no("Not confirmed: the student neither spelled out this exact spelling nor said yes to you reading "
                       "exactly this spelling back. Read the full spelling back once, letter by letter, and pass the "
                       "student's yes as evidence.")
        self.spelling_failures.pop(fact.id, None)
        problem = self._check_value(fact.field, spelled)
        if problem:
            return _no(problem)
        if fact.field == "experience":
            fact.extra["employer"] = spelled
        else:
            fact.value = spelled
        fact.status = "confirmed"
        fact.updated_at = time.time()
        self._replace_everywhere(current, spelled, skip=fact)
        self._changed()
        return _ok(f"Spelling confirmed: {spelled}.", checklist=self.checklist())

    # ----- suggestions for the draft CV ------------------------------------------------------

    SUGGESTABLE = {"skill", "tool", "project", "duty", "summary"}

    def suggest_line(self, name: str, value: str, based_on: str, experience_id: str = "") -> dict[str, Any]:
        """Add a line the agent wrote for the draft CV. It shows as "Suggested" and blocks
        export until the student taps Keep (or edits or removes it) on the Check screen.

        Skills and tools may be typical for the trade; duties, projects and the summary
        must grow from the student's own words. Facts (employers, certificates, dates,
        numbers) are never suggested.
        """
        value = " ".join(str(value or "").split())
        if name not in self.SUGGESTABLE:
            return _no(f"Only {', '.join(sorted(self.SUGGESTABLE))} can be suggested. Ask the student for anything else.")
        problem = self._check_value(name, value)
        if problem:
            return _no(problem)
        if not self.student_said(based_on):
            return _no("based_on must be the student's own words from the transcript.")
        for run in re.findall(r"\d+", normalize(value)):
            if not number_said(run, based_on):
                return _no(f"The number {run} is not in the student's words. Don't put numbers in suggestions.")
        if name in {"duty", "project", "summary"} and _mostly_ascii(based_on) and _content_stems(value) \
                and not (_content_stems(value) & _content_stems(based_on)):
            return _no("A duty, project or summary must grow from what the student said. Base it on their words.")
        if name == "duty":
            parent = self.get(experience_id)
            if not parent or parent.field != "experience":
                return _no("Unknown experience_id.")
            if len(self.duties(experience_id)) >= MAX_DUTIES:
                return _no(f"Keep at most {MAX_DUTIES} duties per job.")
        elif name == "summary":
            if self.single("summary"):
                return _no("There is already a summary. remove_line it first to suggest a new one.")
        else:
            if any(f.value.casefold() == value.casefold() for f in self.values(name)):
                return _ok("Already in the notebook.")
            if len(self.values(name)) >= LIST_FIELDS[name]["max"]:
                return _no("That section is full.")
        section = "experience" if name == "duty" else (SINGLE_FIELDS.get(name) or LIST_FIELDS[name])["section"]
        fact = Fact(uuid.uuid4().hex[:10], name, section, value, based_on, source="agent_draft",
                    status="suggested", parent=experience_id if name == "duty" else "")
        self.facts.append(fact)
        self._changed()
        return _ok("Suggested. It is highlighted for the student to keep or remove.", fact_id=fact.id)

    def keep_line(self, fact_id: str) -> dict[str, Any]:
        """The student tapped Keep on a suggested line, or 'Spelled right' on a name."""
        fact = self.get(fact_id)
        if not fact:
            return _no("No such line.")
        if fact.status == "suggested":
            fact.status, fact.source = "draft", "student_kept"
        elif fact.status == "needs_spelling":
            fact.status = "confirmed"
        else:
            return _ok("Nothing to confirm.")
        fact.updated_at = time.time()
        self._changed()
        return _ok("Kept.")

    def suggested(self) -> list[Fact]:
        return [f for f in self.facts if f.status == "suggested"]

    def remove(self, fact_id: str) -> dict[str, Any]:
        fact = self.get(fact_id)
        if not fact:
            return _no("No such line.")
        self.facts = [f for f in self.facts if f.id != fact_id and f.parent != fact_id]
        self._changed()
        return _ok("Removed.", checklist=self.checklist())

    # ----- writes from the student's own review ------------------------------------------

    def student_edit(self, fact_id: str, value: str, part: str = "value") -> dict[str, Any]:
        """The student typed this line themselves, so it is its own evidence (F9)."""
        value = " ".join(str(value or "").split())
        fact = self.get(fact_id)
        if not fact:
            return _no("No such line.")
        problem = self._check_value(fact.field, value)
        if problem:
            return _no(problem)
        old = fact.extra.get(part, "") if part != "value" else fact.value
        if part == "value":
            fact.value = value
        elif part in fact.extra:
            fact.extra[part] = value
        else:
            return _no("Unknown part of the line.")
        fact.evidence, fact.source = value, "student_edit"
        if fact.status == "suggested":
            fact.status = "draft"  # edited by the student: now their own line
        if fact.status == "needs_spelling" and (part == "employer" or fact.field != "experience"):
            fact.status = "confirmed"
        if SINGLE_FIELDS.get(fact.field, {}).get("spelling") or part == "employer":
            self._replace_everywhere(old, value, skip=fact)
        fact.updated_at = time.time()
        self._changed()
        return _ok("Updated.")

    def approve_review(self) -> dict[str, Any]:
        blockers = self.export_blockers(include_review=False)
        if blockers:
            return _no("Finish these first: " + "; ".join(blockers))
        self.reviewed = True
        return _ok("Checked. Next, choose a style.")

    # ----- status ---------------------------------------------------------------------

    def checklist(self) -> list[dict[str, Any]]:
        items = []
        for key, label in REQUIRED:
            if key == "contact":
                done = bool(self.single("phone") or self.single("email"))
            elif key == "skill":
                done = bool(self.values("skill"))
            else:
                done = bool(self.single(key))
            items.append({"key": key, "label": label, "done": done})
        return items

    def depth_hints(self) -> list[str]:
        """Where the CV is still thin, as questions for the interviewer to ask next."""
        hints = []
        skills = len(self.values("skill"))
        if skills < DEPTH_TARGETS["skill"]:
            hints.append(f"Only {skills} skill(s). Ask about specific jobs they can do: installations, repairs, "
                         "maintenance, fault finding, reading drawings, safety practice.")
        tools = len(self.values("tool"))
        if tools < DEPTH_TARGETS["tool"]:
            hints.append(f"Only {tools} tool(s). Ask which hand tools, power tools, machines, meters or software they can use.")
        experiences = self.values("experience")
        for exp in experiences:
            duties = len(self.duties(exp.id))
            if duties < DEPTH_TARGETS["duty"]:
                where = exp.extra.get("employer") or exp.value
                hints.append(f"Only {duties} duty/duties at {where}. Ask what else they did there: what work, "
                             "for whom, how often or how many, which equipment.")
        if not experiences:
            hints.append("No apprenticeship or job yet. Ask about apprenticeship, OJT, part-time or family work.")
        if len(self.values("project")) < DEPTH_TARGETS["project"]:
            hints.append("No projects. Ask about workshop projects, practical training or OJT done during the course.")
        if not self.values("certification"):
            hints.append("No certificates. Ask about NCVT/SCVT trade certificate, apprenticeship certificate (NAC), "
                         "or other short courses.")
        if not self.single("summary") and all(item["done"] for item in self.checklist()):
            hints.append("No profile summary. Write 2 short lines using only saved facts (trade, training, experience, "
                         "top skills), read it to the student, and save it with their yes plus the quotes it uses.")
        return hints

    def unconfirmed_spellings(self) -> list[str]:
        out = []
        for fact in self.facts:
            if fact.status == "needs_spelling":
                if fact.field == "experience":
                    out.append(f"Spelling of employer '{fact.extra.get('employer', '')}'")
                else:
                    out.append(f"Spelling of {SINGLE_FIELDS[fact.field]['label'].lower()} '{fact.value}'")
        return out

    def export_blockers(self, include_review: bool = True) -> list[str]:
        blockers = [f"Missing: {item['label']}" for item in self.checklist() if not item["done"]]
        blockers += self.unconfirmed_spellings()
        pending = len(self.suggested())
        if pending:
            blockers.append(f"{pending} suggested line{'s' if pending != 1 else ''} to keep or remove")
        if include_review and not self.reviewed:
            blockers.append("The student has not reviewed the full CV yet")
        return blockers

    def to_dict(self) -> dict[str, Any]:
        def label(f: Fact) -> str:
            if f.field in SINGLE_FIELDS:
                return SINGLE_FIELDS[f.field]["label"]
            if f.field in LIST_FIELDS:
                return LIST_FIELDS[f.field]["label"]
            return "Job or apprenticeship" if f.field == "experience" else "Duty"

        return {
            "facts": [{**asdict(f), "label": label(f)} for f in self.facts],
            "checklist": self.checklist(),
            "unconfirmed_spellings": self.unconfirmed_spellings(),
            "export_blockers": self.export_blockers(),
            "reviewed": self.reviewed,
            "revision": self.revision,
        }
