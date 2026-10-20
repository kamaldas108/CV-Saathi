import os
import sys
from pathlib import Path

import pytest

# Tests never call a model: force sample mode before the server module loads.
os.environ["CVS_SAMPLE_MODE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cvsaathi.notebook import CvNotebook  # noqa: E402

STUDENT = (
    "My name is Ravi Kumar. My number is 9845012345 and email ravi.k@gmail.com. I live in Mysuru. "
    "I studied Electrician at Government ITI Mysuru and passed in 2024. "
    "I did apprenticeship as electrician at KPTCL for 1 year. I fix motors, I do house wiring and panel wiring. "
    "I speak Kannada, Hindi and English."
)


def full_notebook(skills: int = 6, confirm: bool = True) -> CvNotebook:
    """A complete notebook built through the same rules the voice model must pass."""
    nb = CvNotebook()
    skill_names = [f"Skilltopic{i} work" for i in range(skills)]
    nb.add_turn("student", STUDENT + " Skills: " + ", ".join(skill_names))
    said = nb.transcript[0]["text"]
    for name, value in [
        ("full_name", "Ravi Kumar"), ("phone", "9845012345"), ("email", "ravi.k@gmail.com"), ("city", "Mysuru"),
        ("trade", "Electrician"), ("institute", "Government ITI Mysuru"), ("passing_year", "2024"),
    ]:
        assert nb.save_field(name, value, said)["ok"], name
    exp = nb.add_experience("Apprentice Electrician", "KPTCL", "1 year", said)
    assert exp["ok"], exp
    for duty in ["Repaired and serviced electric motors", "Did house wiring", "Did panel wiring"]:
        assert nb.add_duty(exp["experience_id"], duty, said)["ok"], duty
    for skill in skill_names:
        assert nb.save_field("skill", skill.capitalize(), said)["ok"], skill
    for language in ["Kannada", "Hindi", "English"]:
        assert nb.save_field("language", language, said)["ok"]
    if confirm:
        nb.add_turn("student", "yes")
        for target in ["full_name", "city", "institute"]:
            assert nb.confirm_spelling(target, nb.single(target).value, "yes")["ok"]
        assert nb.confirm_spelling(exp["experience_id"], "KPTCL", "yes")["ok"]
    return nb


@pytest.fixture
def notebook() -> CvNotebook:
    return full_notebook()
