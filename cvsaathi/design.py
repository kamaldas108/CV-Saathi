"""Template settings and the design changes a student can ask for (F6, F7).

The voice model turns "make it blue" into a structured set_design call. The sample
mode, which has no model, uses parse_request for a small set of English phrasings.
Either way, apply_changes is the only thing that changes the settings, and it
refuses anything outside the supported list with a short explanation.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

TEMPLATES = {
    "classic": "Classic",
    "modern": "Modern",
    "compact": "Compact",
    "bold": "Bold",
}
ACCENTS: dict[str, tuple[int, int, int]] = {
    "navy": (31, 58, 95),
    "blue": (29, 86, 178),
    "teal": (0, 112, 112),
    "green": (30, 115, 60),
    "maroon": (125, 30, 45),
    "purple": (92, 55, 140),
    "orange": (190, 90, 20),
    "black": (25, 25, 25),
    "grey": (85, 85, 85),
}
ACCENT_ALIASES = {
    "gray": "grey", "red": "maroon", "dark blue": "navy", "sky blue": "blue", "light blue": "blue",
    "dark green": "green", "violet": "purple", "brown": "maroon",
}
FONT_PAIRS: dict[str, dict[str, str]] = {
    "sans": {"label": "Simple (sans-serif)", "heading": "helvetica", "body": "helvetica"},
    "serif": {"label": "Formal (serif)", "heading": "times", "body": "times"},
    "mixed": {"label": "Serif headings, simple text", "heading": "times", "body": "helvetica"},
}
SECTIONS = ["summary", "experience", "skills", "tools", "education", "projects", "languages"]
SECTION_TITLES = {
    "summary": "Profile",
    "experience": "Apprenticeship and Work Experience",
    "skills": "Skills",
    "tools": "Tools and Equipment",
    "education": "Education",
    "projects": "Projects and Practical Training",
    "languages": "Languages",
}
DENSITIES = ["comfortable", "compact"]

SUPPORTED_HELP = (
    "I can change the colour, the font, the order of sections, the spacing, "
    "the template, or turn the photo on or off."
)


@dataclass
class DesignSettings:
    template: str = "classic"
    accent: str = "navy"
    font_pair: str = "sans"
    section_order: list[str] = field(default_factory=lambda: list(SECTIONS))
    photo: bool = False
    density: str = "comfortable"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _move(order: list[str], section: str, place: str, relative_to: str | None) -> list[str]:
    rest = [s for s in order if s != section]
    if place == "top":
        return [section, *rest]
    if place == "bottom":
        return [*rest, section]
    index = rest.index(relative_to)  # type: ignore[arg-type]
    return [*rest[: index + (place == "below")], section, *rest[index + (place == "below"):]]


def apply_changes(settings: DesignSettings, changes: dict[str, Any], *, has_photo: bool = False) -> dict[str, Any]:
    """Apply a structured design change. Returns what was applied and what was refused."""
    applied: list[str] = []
    refused: list[str] = []
    new = DesignSettings(**{**settings.to_dict(), "section_order": list(settings.section_order)})

    template = changes.get("template")
    if template:
        if template in TEMPLATES:
            new.template = template
            applied.append(f"template {TEMPLATES[template]}")
        else:
            refused.append(f"There is no '{template}' template. Choose {', '.join(TEMPLATES.values())}.")

    accent = changes.get("accent_color")
    if accent:
        accent = ACCENT_ALIASES.get(str(accent).lower(), str(accent).lower())
        if accent in ACCENTS:
            new.accent = accent
            applied.append(f"colour {accent}")
        else:
            refused.append(f"I can't use '{changes['accent_color']}'. Colours available: {', '.join(ACCENTS)}.")

    font = changes.get("font_pair")
    if font:
        if font in FONT_PAIRS:
            new.font_pair = font
            applied.append(f"font {FONT_PAIRS[font]['label'].lower()}")
        else:
            refused.append(f"Fonts available: {', '.join(p['label'] for p in FONT_PAIRS.values())}.")

    section = changes.get("move_section")
    if section:
        place = changes.get("place", "top")
        relative_to = changes.get("relative_to")
        if section not in SECTIONS:
            refused.append(f"There is no '{section}' section. Sections: {', '.join(SECTIONS)}.")
        elif place not in {"top", "bottom", "above", "below"}:
            refused.append("Say where to move it: top, bottom, above or below another section.")
        elif place in {"above", "below"} and (relative_to not in SECTIONS or relative_to == section):
            refused.append("Say which other section it should go above or below.")
        else:
            new.section_order = _move(new.section_order, section, place, relative_to)
            where = place if place in {"top", "bottom"} else f"{place} {relative_to}"
            applied.append(f"{section} moved {where}")

    if "photo" in changes and changes["photo"] is not None:
        wanted = bool(changes["photo"])
        if wanted and not has_photo:
            refused.append("There is no photo yet. Adding a photo comes in the next version of the app.")
        else:
            new.photo = wanted
            applied.append("photo on" if wanted else "photo off")

    density = changes.get("density")
    if density:
        if density in DENSITIES:
            new.density = density
            applied.append(f"{density} spacing")
        else:
            refused.append("Spacing can be comfortable or compact.")

    if not applied and not refused:
        refused.append(SUPPORTED_HELP)
    if applied:
        settings.__dict__.update(new.__dict__)
    return {"ok": bool(applied), "applied": applied, "refused": refused, "settings": settings.to_dict()}


# ----- sample-mode phrase parser --------------------------------------------------------

_SECTION_WORDS = {
    "summary": "summary", "profile": "summary", "objective": "summary",
    "tools": "tools", "tool": "tools", "equipment": "tools", "machines": "tools",
    "skills": "skills", "skill": "skills",
    "education": "education", "study": "education", "studies": "education", "course": "education",
    "experience": "experience", "apprenticeship": "experience", "work": "experience", "job": "experience", "jobs": "experience",
    "projects": "projects", "project": "projects", "training": "projects",
    "languages": "languages", "language": "languages",
}
_VAGUE = ["royal", "nice", "beautiful", "professional", "attractive", "stylish", "fancy", "good looking", "better", "impressive"]
VAGUE_OPTIONS = [
    {"label": "Navy with formal serif font", "changes": {"accent_color": "navy", "font_pair": "serif"}},
    {"label": "Maroon, Bold template", "changes": {"accent_color": "maroon", "template": "bold"}},
    {"label": "Purple, Modern template", "changes": {"accent_color": "purple", "template": "modern"}},
]


def _section_in(text: str) -> list[str]:
    found = []
    for word in re.findall(r"[a-z]+", text):
        section = _SECTION_WORDS.get(word)
        if section and section not in found:
            found.append(section)
    return found


def parse_request(text: str) -> dict[str, Any]:
    """Turn a typed or transcribed English request into changes, or explain why not."""
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    changes: dict[str, Any] = {}

    for name in TEMPLATES:
        if re.search(rf"\b{name}\b (template|design|style|layout)|(template|design|style|layout) \b{name}\b", t):
            changes["template"] = name
    for alias, accent in sorted({**ACCENT_ALIASES, **{a: a for a in ACCENTS}}.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{alias}\b", t):
            changes["accent_color"] = accent
            break
    if re.search(r"\b(serif|formal|times)\b.*\bfont|\bfont\b.*\b(serif|formal|times)\b", t) and "sans" not in t:
        changes["font_pair"] = "serif"
    elif re.search(r"\b(sans|simple|plain|clean)\b.*\bfont|\bfont\b.*\b(sans|simple|plain|clean)\b", t):
        changes["font_pair"] = "sans"
    elif re.search(r"\bmixed\b.*\bfont|\bfont\b.*\bmixed\b", t):
        changes["font_pair"] = "mixed"

    sections = _section_in(t)
    if sections and re.search(r"\b(put|move|above|below|before|after|first|top|last|bottom|up|down)\b", t):
        section = sections[0]
        if len(sections) > 1 and re.search(r"\b(above|before)\b", t):
            changes.update(move_section=section, place="above", relative_to=sections[1])
        elif len(sections) > 1 and re.search(r"\b(below|after|under)\b", t):
            changes.update(move_section=section, place="below", relative_to=sections[1])
        elif re.search(r"\b(last|bottom|end|down)\b", t):
            changes.update(move_section=section, place="bottom")
        elif re.search(r"\b(first|top|up|start)\b", t):
            changes.update(move_section=section, place="top")

    if re.search(r"\b(remove|no|without|hide|delete)\b.*\bphoto\b|\bphoto\b.*\b(off|remove)\b", t):
        changes["photo"] = False
    elif re.search(r"\b(add|put|show|with|include)\b.*\bphoto\b|\bphoto\b.*\bon\b", t):
        changes["photo"] = True

    if "template" not in changes:
        if re.search(r"\b(compact|tighter|tight|fit more|less space|smaller)\b", t):
            changes["density"] = "compact"
        elif re.search(r"\b(more space|spacious|spread|less crowded|comfortable|bigger)\b", t):
            changes["density"] = "comfortable"

    if changes:
        return {"changes": changes}
    if any(re.search(rf"\b{word}\b", t) for word in _VAGUE):
        return {"vague": True, "message": "Here are some options: " + "; ".join(o["label"] for o in VAGUE_OPTIONS) + ". Which one?", "options": VAGUE_OPTIONS}
    return {"unsupported": True, "message": "Sorry, I can't do that. " + SUPPORTED_HELP}
