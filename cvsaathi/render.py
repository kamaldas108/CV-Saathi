"""Turn the notebook into the CV: one A4 PDF page, a PNG preview, and plain text (F6, F10).

All four templates are single-column with real (selectable) text, so applicant
tracking systems can read them. Graphics (the key-facts strip, bullet dots, language
stars) are drawn alongside the text, never instead of it: a language shows both its
stars and "(Fluent)".

The layout picks the largest text size that still fits on one page, then spreads the
sections out so a short CV fills the page instead of ending halfway down.
"""

from __future__ import annotations

import io
import re
import threading
import unicodedata
from typing import Any

import pypdfium2 as pdfium
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .design import ACCENTS, FONT_PAIRS, SECTION_TITLES, DesignSettings
from .notebook import CvNotebook

PAGE_W, PAGE_H = 210.0, 297.0
# Largest first: a short CV gets big, readable text; a long one shrinks until it fits.
SCALES = [1.3, 1.22, 1.15, 1.08, 1.0, 0.94, 0.88, 0.82, 0.76, 0.70, 0.64]
MAX_SECTION_GAP = 9.0  # mm of extra space per section when spreading a short CV
SEP = "  ·  "  # middle dot is in Latin-1, so the core fonts can print it
GRID_ITEM_MAX = 34  # items up to this length go in two columns
# pdfium is not thread-safe, and the web server renders thumbnails in parallel threads.
# Without this lock, four thumbnails at once crashed the whole server process.
_PDFIUM = threading.RLock()

LEVELS = {
    "basic": 2, "beginner": 2, "elementary": 2,
    "good": 3, "intermediate": 3, "working": 3,
    "fluent": 4, "very good": 4, "advanced": 4,
    "native": 5, "mother tongue": 5, "excellent": 5, "first language": 5,
}
_LEVEL_RE = re.compile(r"^(.*?)\s*[(\-:–]\s*([A-Za-z ]+?)\s*\)?\s*$")


class CvTooLong(Exception):
    """Raised when the content cannot fit on one page even at the smallest size."""


def clean(text: str) -> str:
    """Map text to Latin-1, which the built-in PDF fonts support."""
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("•", "-").replace("…", "...")
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        decomposed = unicodedata.normalize("NFKD", text)
        return decomposed.encode("latin-1", "ignore").decode("latin-1")


def language_rating(value: str) -> tuple[str, int, str]:
    """'Kannada (Native)' -> ('Kannada', 5, 'Native'). No level said -> 0 stars."""
    match = _LEVEL_RE.match(value.strip())
    if match and match.group(2).strip().lower() in LEVELS:
        level = match.group(2).strip()
        return match.group(1).strip(), LEVELS[level.lower()], level.capitalize()
    return value.strip(), 0, ""


# ----- content -----------------------------------------------------------------------------


def cv_content(nb: CvNotebook) -> dict[str, Any]:
    """The CV as ordered data, shared by the PDF and the plain-text version."""

    def one(name: str) -> str:
        fact = nb.single(name)
        return fact.value if fact else ""

    contact = [x for x in (one("phone"), one("email"), one("city")) if x]
    sections: dict[str, list[dict[str, Any]]] = {}
    experiences = nb.values("experience")

    sections["experience"] = [
        {
            "title": exp.value,
            "subtitle": SEP.join(x for x in (exp.extra.get("employer", ""), exp.extra.get("duration", "")) if x),
            "bullets": [d.value for d in nb.duties(exp.id)],
        }
        for exp in experiences
    ]
    sections["summary"] = [{"text": one("summary")}] if one("summary") else []
    skills = [f.value for f in nb.values("skill")]
    if skills:
        short = max(len(s) for s in skills) <= GRID_ITEM_MAX
        sections["skills"] = [{"grid": skills}] if short else [{"title": "", "subtitle": "", "bullets": skills}]
    else:
        sections["skills"] = []
    tools = [f.value for f in nb.values("tool")]
    sections["tools"] = [{"grid": tools}] if tools else []

    education: list[dict[str, Any]] = []
    if one("qualification") or one("institute") or one("passing_year"):
        title = one("qualification") or (f"ITI - {one('trade')}" if one("trade") else "ITI")
        education.append({
            "title": title,
            "subtitle": SEP.join(x for x in (one("institute"), one("passing_year") and f"Passed {one('passing_year')}") if x),
            "bullets": [],
        })
    certs = [f.value for f in nb.values("certification")]
    if certs:
        education.append({"title": "", "subtitle": "", "bullets": certs})
    sections["education"] = education
    projects = [f.value for f in nb.values("project")]
    sections["projects"] = [{"title": "", "subtitle": "", "bullets": projects}] if projects else []
    languages = [f.value for f in nb.values("language")]
    sections["languages"] = [{"ratings": [language_rating(v) for v in languages], "raw": languages}] if languages else []

    # Key facts for the strip under the name: only facts the student gave.
    facts = []
    if one("trade"):
        facts.append(("Trade", one("trade")))
    if one("passing_year"):
        facts.append(("ITI passed", one("passing_year")))
    if experiences:
        first = experiences[0]
        facts.append(("Experience", first.extra.get("duration") or first.value))
    if one("city"):
        facts.append(("Based in", one("city")))

    return {
        "name": one("full_name") or "Your Name",
        "headline": one("trade"),
        "contact": contact,
        "facts": facts if len(facts) >= 2 else [],
        "sections": sections,
    }


def cv_text(nb: CvNotebook, settings: DesignSettings) -> str:
    """Plain-text CV for pasting into job portals."""
    content = cv_content(nb)
    lines = [content["name"]]
    if content["headline"]:
        lines.append(content["headline"])
    if content["contact"]:
        lines.append(" | ".join(content["contact"]))
    for key in settings.section_order:
        items = content["sections"].get(key) or []
        if not items:
            continue
        lines += ["", SECTION_TITLES[key].upper()]
        for item in items:
            if "text" in item:
                lines.append(item["text"])
            elif "grid" in item:
                lines.append(", ".join(item["grid"]))
            elif "ratings" in item:
                lines.append(", ".join(item["raw"]))
            else:
                if item.get("title"):
                    lines.append(item["title"])
                if item.get("subtitle"):
                    lines.append(item["subtitle"].replace(SEP, " | "))
                lines += [f"- {b}" for b in item.get("bullets", [])]
    return "\n".join(lines).strip() + "\n"


# ----- PDF ---------------------------------------------------------------------------------


def _tint(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Mix a colour with white: amount 0.9 gives a very light tint."""
    return tuple(round(c + (255 - c) * amount) for c in rgb)  # type: ignore[return-value]


class _Cv(FPDF):
    def __init__(self, settings: DesignSettings, scale: float, section_gap: float = 0.0) -> None:
        super().__init__(format="A4", unit="mm")
        self.s = settings
        self.scale = scale
        self.space = scale * (0.85 if settings.density == "compact" else 1.0)
        self.section_gap = section_gap
        self.accent = ACCENTS.get(settings.accent, ACCENTS["navy"])
        fonts = FONT_PAIRS.get(settings.font_pair, FONT_PAIRS["sans"])
        self.head_font, self.body_font = fonts["heading"], fonts["body"]
        margin = 15 if settings.template != "compact" else 13
        self.set_margins(margin, margin, margin)
        self.set_auto_page_break(True, margin)
        self.set_creator("CV-Saathi")

    def fs(self, size: float) -> float:
        return size * self.scale

    def sp(self, mm: float) -> float:
        return mm * self.space

    def line_h(self, size: float) -> float:
        return self.fs(size) * 0.42 + self.sp(1.0)

    @property
    def text_w(self) -> float:
        return PAGE_W - self.l_margin - self.r_margin

    def body(self, size: float = 10.5, style: str = "") -> None:
        self.set_font(self.body_font, style, self.fs(size))
        self.set_text_color(35, 35, 35)

    def write_block(self, text: str, size: float = 10.5, style: str = "", indent: float = 0, color=None,
                    width: float | None = None, x: float | None = None) -> None:
        self.body(size, style)
        if color:
            self.set_text_color(*color)
        self.set_x((self.l_margin if x is None else x) + indent)
        self.multi_cell((width or self.text_w) - indent, self.line_h(size), clean(text), align="L",
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def dot(self, x: float, y: float, size: float) -> None:
        d = 1.15 * self.scale
        self.set_fill_color(*self.accent)
        self.ellipse(x, y + self.line_h(size) / 2 - d / 2, d, d, style="F")

    def bullet(self, text: str, size: float = 10.5, x: float | None = None, width: float | None = None) -> None:
        left = self.l_margin if x is None else x
        self.dot(left + 1.2, self.get_y(), size)
        self.write_block(text, size, indent=5, x=left, width=width)

    def grid(self, items: list[str], size: float = 10.5) -> None:
        """Two columns of bulleted items, filled row by row."""
        gap = 6.0
        col = (self.text_w - gap) / 2
        for i in range(0, len(items), 2):
            top = self.get_y()
            bottoms = []
            for j, item in enumerate(items[i:i + 2]):
                self.set_y(top)
                self.bullet(item, size, x=self.l_margin + j * (col + gap), width=col)
                bottoms.append(self.get_y())
            self.set_y(max(bottoms) + self.sp(0.4))

    def ratings(self, rows: list[tuple[str, int, str]], size: float = 10.5) -> None:
        """Languages in two columns: name, five stars, and the level as text."""
        gap = 6.0
        col = (self.text_w - gap) / 2
        h = self.line_h(size) + self.sp(0.8)
        for i in range(0, len(rows), 2):
            top = self.get_y()
            for j, (name, stars, level) in enumerate(rows[i:i + 2]):
                x = self.l_margin + j * (col + gap)
                self.body(size, "B")
                self.set_xy(x, top)
                self.cell(col * 0.36, h, clean(name))
                if stars:
                    r = 1.55 * self.scale
                    cx = x + col * 0.38 + r
                    for k in range(5):
                        filled = k < stars
                        self.set_fill_color(*(self.accent if filled else _tint(self.accent, 0.82)))
                        self.set_draw_color(*(self.accent if filled else _tint(self.accent, 0.6)))
                        self.star(cx + k * (2 * r + 1.0), top + h / 2, r * 0.45, r, 5, rotate_degrees=-90, style="DF")
                    self.body(size - 1.5)
                    self.set_text_color(95, 95, 95)
                    self.set_xy(cx + 5 * (2 * r + 1.0) - r + 1.0, top)
                    self.cell(col * 0.25, h, f"({clean(level)})")
            self.set_y(top + h)


def _header(pdf: _Cv, content: dict[str, Any]) -> None:
    t = pdf.s.template
    name, headline, contact = clean(content["name"]), clean(content["headline"]), clean(SEP.join(content["contact"]))
    if t == "modern":
        band_h = pdf.fs(30) * (1 if not contact else 1.15)
        pdf.set_fill_color(*pdf.accent)
        pdf.rect(0, 0, PAGE_W, band_h, style="F")
        pdf.set_y(pdf.fs(7))
        pdf.set_font(pdf.head_font, "B", pdf.fs(24))
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, pdf.fs(10), name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if headline:
            pdf.set_font(pdf.body_font, "", pdf.fs(12))
            pdf.cell(0, pdf.fs(6), headline, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if contact:
            pdf.set_font(pdf.body_font, "", pdf.fs(10))
            pdf.cell(0, pdf.fs(6), contact, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_y(band_h + pdf.sp(5))
        return
    align = "C" if t == "classic" else "L"
    size = {"classic": 24, "compact": 20, "bold": 30}[t]
    pdf.set_font(pdf.head_font, "B", pdf.fs(size))
    pdf.set_text_color(*(pdf.accent if t in {"classic", "bold"} else (20, 20, 20)))
    pdf.cell(0, pdf.fs(size) * 0.5, name.upper() if t == "bold" else name, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(pdf.sp(1.5))
    if headline:
        pdf.set_font(pdf.body_font, "B" if t == "bold" else "", pdf.fs(12))
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, pdf.fs(6), headline, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if contact:
        pdf.set_font(pdf.body_font, "", pdf.fs(10))
        pdf.set_text_color(70, 70, 70)
        pdf.cell(0, pdf.fs(6), contact, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(pdf.sp(2))
    if t in {"classic", "compact"}:
        pdf.set_draw_color(*pdf.accent)
        pdf.set_line_width(0.7 if t == "classic" else 0.35)
        pdf.line(pdf.l_margin, pdf.get_y(), PAGE_W - pdf.r_margin, pdf.get_y())
    pdf.ln(pdf.sp(3))


def _facts_strip(pdf: _Cv, facts: list[tuple[str, str]]) -> None:
    """A small table of key facts under the header: trade, year passed, experience, city."""
    if not facts:
        return
    gap = 3.0
    cell_w = (pdf.text_w - gap * (len(facts) - 1)) / len(facts)
    h = pdf.fs(13.5)
    top = pdf.get_y()
    for i, (label, value) in enumerate(facts):
        x = pdf.l_margin + i * (cell_w + gap)
        pdf.set_fill_color(*_tint(pdf.accent, 0.9))
        pdf.rect(x, top, cell_w, h, style="F")
        pdf.set_fill_color(*pdf.accent)
        pdf.rect(x, top, 1.4, h, style="F")
        pdf.set_xy(x + 3.5, top + pdf.fs(1.8))
        pdf.set_font(pdf.body_font, "B", pdf.fs(7.5))
        pdf.set_text_color(*pdf.accent)
        pdf.cell(cell_w - 5, pdf.fs(4), clean(label.upper()))
        pdf.set_xy(x + 3.5, top + pdf.fs(6.3))
        pdf.set_font(pdf.body_font, "B", pdf.fs(10.5))
        pdf.set_text_color(30, 30, 30)
        value = clean(value)
        while pdf.get_string_width(value) > cell_w - 5 and len(value) > 4:
            value = value[:-2]
        pdf.cell(cell_w - 5, pdf.fs(5), value)
    pdf.set_y(top + h + pdf.sp(3))


def _section_heading(pdf: _Cv, title: str) -> None:
    t = pdf.s.template
    pdf.ln(pdf.sp(3.2) + pdf.section_gap)
    if t == "bold":
        pdf.set_fill_color(*pdf.accent)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(pdf.head_font, "B", pdf.fs(11.5))
        pdf.cell(0, pdf.fs(7.2), "  " + clean(title.upper()), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(pdf.sp(1.8))
        return
    pdf.set_font(pdf.head_font, "B", pdf.fs(12 if t != "compact" else 11.5))
    pdf.set_text_color(*(pdf.accent if t != "compact" else (20, 20, 20)))
    y = pdf.get_y()
    if t in {"modern", "classic"}:
        # A small accent marker before the title.
        pdf.set_fill_color(*pdf.accent)
        if t == "modern":
            pdf.rect(pdf.l_margin, y + 1, 1.8, pdf.fs(4.4), style="F")
        else:
            d = pdf.fs(2.4)
            pdf.ellipse(pdf.l_margin, y + pdf.fs(3.3) - d / 2, d, d, style="F")
        pdf.set_x(pdf.l_margin + 4.2)
    pdf.cell(0, pdf.fs(6.6), clean(title.upper() if t in {"classic", "compact"} else title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if t in {"classic", "compact"}:
        pdf.set_draw_color(*_tint(pdf.accent, 0.35))
        pdf.set_line_width(0.3)
        pdf.line(pdf.l_margin, pdf.get_y(), PAGE_W - pdf.r_margin, pdf.get_y())
    pdf.ln(pdf.sp(2))


def _build(content: dict[str, Any], settings: DesignSettings, scale: float, section_gap: float = 0.0) -> _Cv:
    pdf = _Cv(settings, scale, section_gap)
    pdf.set_title(clean(f"CV - {content['name']}"))
    pdf.add_page()
    _header(pdf, content)
    _facts_strip(pdf, content["facts"])
    for key in settings.section_order:
        items = content["sections"].get(key) or []
        if not items:
            continue
        _section_heading(pdf, SECTION_TITLES[key])
        for item in items:
            if "text" in item:
                pdf.write_block(item["text"], 10.5)
            elif "grid" in item:
                pdf.grid(item["grid"])
            elif "ratings" in item:
                pdf.ratings(item["ratings"])
            else:
                if item.get("title"):
                    pdf.write_block(item["title"], 11.5, "B")
                if item.get("subtitle"):
                    pdf.write_block(item["subtitle"], 10, "I", color=(85, 85, 85))
                for text in item.get("bullets", []):
                    pdf.bullet(text)
                pdf.ln(pdf.sp(1.2))
    return pdf


def _sections_used(content: dict[str, Any], settings: DesignSettings) -> int:
    return sum(1 for key in settings.section_order if content["sections"].get(key))


def render_pdf(nb: CvNotebook, settings: DesignSettings) -> bytes:
    """Render the CV to exactly one A4 page: the largest text that fits, spread to fill the page."""
    with _PDFIUM:  # one render at a time: parallel renders corrupted thumbnails (missing letters)
        return _render_pdf(nb, settings)


def _render_pdf(nb: CvNotebook, settings: DesignSettings) -> bytes:
    content = cv_content(nb)
    for scale in SCALES:
        pdf = _build(content, settings, scale)
        if pdf.pages_count != 1:
            continue
        # Spread a short CV down the page instead of leaving the bottom half empty.
        leftover = (PAGE_H - pdf.b_margin) - pdf.get_y() - 2
        sections = _sections_used(content, settings)
        if leftover > 8 and sections:
            gap = min(leftover / (sections + 1), MAX_SECTION_GAP)
            spread = _build(content, settings, scale, gap)
            if spread.pages_count == 1:
                pdf = spread
        return bytes(pdf.output())
    raise CvTooLong("The CV does not fit on one page. Remove some lines and try again.")


# Every pdfium object is closed explicitly inside the lock. Left to Python's garbage
# collector, they would be freed later on another thread, outside the lock, which
# crashed the server intermittently.


def pdf_page_count(data: bytes) -> int:
    with _PDFIUM:
        doc = pdfium.PdfDocument(data)
        try:
            return len(doc)
        finally:
            doc.close()


def pdf_text(data: bytes) -> str:
    with _PDFIUM:
        doc = pdfium.PdfDocument(data)
        try:
            parts = []
            for i in range(len(doc)):
                page = doc[i]
                textpage = page.get_textpage()
                parts.append(textpage.get_text_range())
                textpage.close()
                page.close()
            return "\n".join(parts)
        finally:
            doc.close()


def pdf_to_png(data: bytes, width_px: int = 720) -> bytes:
    with _PDFIUM:
        doc = pdfium.PdfDocument(data)
        try:
            page = doc[0]
            bitmap = page.render(scale=width_px / page.get_width())
            image = bitmap.to_pil().copy()  # copy: the PIL image must not point into pdfium memory
            bitmap.close()
            page.close()
        finally:
            doc.close()
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", clean(name)).strip("_") or "CV"
    return f"{stem}_CV.pdf"
