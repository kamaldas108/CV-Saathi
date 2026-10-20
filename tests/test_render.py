"""PDF (F6, F10): every template renders to exactly one A4 page with selectable text."""

import pypdfium2 as pdfium
import pytest

from cvsaathi.design import TEMPLATES, DesignSettings
from cvsaathi.render import cv_text, pdf_page_count, pdf_text, render_pdf

from .conftest import full_notebook


@pytest.mark.parametrize("template", list(TEMPLATES))
@pytest.mark.parametrize("skills", [6, 12, 20])
@pytest.mark.parametrize("density", ["comfortable", "compact"])
def test_every_template_is_one_a4_page_with_selectable_text(template, skills, density):
    nb = full_notebook(skills=skills)
    pdf = render_pdf(nb, DesignSettings(template=template, density=density, font_pair="serif"))
    assert pdf_page_count(pdf) == 1
    width, height = pdfium.PdfDocument(pdf)[0].get_size()
    assert (round(width), round(height)) == (595, 842)  # A4 in points
    text = pdf_text(pdf)
    assert "Ravi Kumar" in text or "RAVI KUMAR" in text
    assert f"Skilltopic{skills - 1} work" in text
    assert "Repaired and serviced electric motors" in text


def test_largest_allowed_notebook_still_fits_one_page():
    nb = full_notebook(skills=25)
    said = nb.transcript[0]["text"]
    nb.add_turn("student", said + " projects: " + ", ".join(f"Workshop{i} panel board assembly" for i in range(5)))
    said = nb.transcript[-1]["text"]
    for i in range(5):
        assert nb.save_field("project", f"Workshop{i} panel board assembly and testing of circuit breakers", said)["ok"]
    for _ in range(3):
        exp = nb.add_experience("Apprentice Electrician", "KPTCL", "1 year", said)
        for _ in range(6):
            assert nb.add_duty(exp["experience_id"], "Repaired and serviced electric motors in house wiring panels", said)["ok"]
    for template in TEMPLATES:
        assert pdf_page_count(render_pdf(nb, DesignSettings(template=template))) == 1


def test_summary_tools_and_descriptive_skills_render_on_one_page():
    nb = full_notebook(skills=0)
    said = ("I fix taps, sinks and toilets in houses. I use pipe wrench, drill machine, pipe threader. "
            "I am a plumber trained at ITI with one year at Urban Company.")
    nb.add_turn("student", said)
    for skill in ["Installed and repaired taps, sinks and toilets in homes", "Fixed leaking pipes in houses"]:
        assert nb.save_field("skill", skill, said)["ok"]
    for tool in ["Pipe wrench", "Drill machine", "Pipe threader"]:
        assert nb.save_field("tool", tool, said)["ok"]
    summary = "ITI-trained plumber with one year at Urban Company fixing taps, sinks and toilets in homes."
    assert nb.save_field("summary", summary, said)["ok"]
    for template in TEMPLATES:
        pdf = render_pdf(nb, DesignSettings(template=template))
        assert pdf_page_count(pdf) == 1
        text = pdf_text(pdf)
        assert "Pipe threader" in text and "ITI-trained plumber" in text
        assert "Installed and repaired taps, sinks and toilets in homes" in text
    plain = cv_text(nb, DesignSettings())
    assert plain.index("PROFILE") < plain.index("APPRENTICESHIP") < plain.index("SKILLS") < plain.index("TOOLS")


def _lowest_text_y(pdf: bytes) -> float:
    """Distance in mm from the top of the page to the lowest character on it."""
    page = pdfium.PdfDocument(pdf)[0]
    text = page.get_textpage()
    height_pt = page.get_height()
    bottom = min(text.get_charbox(i)[1] for i in range(text.count_chars()) if text.get_text_range(i, 1).strip())
    return (height_pt - bottom) / 72 * 25.4


def test_a_short_cv_fills_most_of_the_page():
    nb = full_notebook(skills=4)
    for template in TEMPLATES:
        pdf = render_pdf(nb, DesignSettings(template=template))
        assert _lowest_text_y(pdf) > 297 * 0.8, template  # not stopping halfway down the page


def test_languages_show_stars_and_the_level_in_text():
    from cvsaathi.render import language_rating

    assert language_rating("Kannada (Native)") == ("Kannada", 5, "Native")
    assert language_rating("English - basic") == ("English", 2, "Basic")
    assert language_rating("Tulu") == ("Tulu", 0, "")
    nb = full_notebook()
    said = "Kannada native, Hindi good"
    nb.add_turn("student", said)
    nb.facts = [f for f in nb.facts if f.field != "language"]
    assert nb.save_field("language", "Kannada (Native)", said)["ok"]
    assert nb.save_field("language", "Hindi (Good)", said)["ok"]
    text = pdf_text(render_pdf(nb, DesignSettings()))
    assert "Kannada" in text and "(Native)" in text and "(Good)" in text  # ATS can read the level


def test_key_facts_table_uses_only_saved_facts():
    nb = full_notebook()
    text = pdf_text(render_pdf(nb, DesignSettings()))
    for label, value in [("TRADE", "Electrician"), ("ITI PASSED", "2024"), ("EXPERIENCE", "1 year"), ("BASED IN", "Mysuru")]:
        assert label in text and value in text


def test_parallel_previews_render_completely():
    # Seen live: four thumbnails rendered at once came out with missing letters, then the
    # server process crashed. pdfium is not thread-safe; rendering is serialised.
    import threading

    from cvsaathi.render import pdf_to_png

    nb = full_notebook(skills=12)
    reference = {t: pdf_text(render_pdf(nb, DesignSettings(template=t))) for t in TEMPLATES}
    problems = []

    def work(template):
        for _ in range(5):
            pdf = render_pdf(nb, DesignSettings(template=template))
            pdf_to_png(pdf, 240)
            if pdf_text(pdf) != reference[template]:
                problems.append(template)

    threads = [threading.Thread(target=work, args=(t,)) for t in list(TEMPLATES) * 2]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert problems == []


def test_section_order_is_followed_in_pdf_and_text():
    nb = full_notebook()
    settings = DesignSettings(section_order=["skills", "languages", "education", "experience", "projects"])
    text = pdf_text(render_pdf(nb, settings))
    assert text.index("SKILLS") < text.index("LANGUAGES") < text.index("EDUCATION")
    plain = cv_text(nb, settings)
    assert plain.index("SKILLS") < plain.index("LANGUAGES") < plain.index("EDUCATION") < plain.index("APPRENTICESHIP")


def test_plain_text_contains_every_line():
    nb = full_notebook()
    plain = cv_text(nb, DesignSettings())
    for fact in nb.facts:
        assert fact.value in plain
