"""Drafting with the text model (mocked): every proposal goes through the suggestion rules."""

from cvsaathi.drafting import Draft, DraftLine, build_prompt, draft_cv

from .conftest import full_notebook


def fake_model(lines):
    return lambda prompt: Draft(lines=[DraftLine(**line) for line in lines])


def test_drafted_lines_arrive_as_suggestions(notebook):
    said = "I fix motors, I do house wiring and panel wiring"
    exp_id = notebook.values("experience")[0].id
    result = draft_cv(notebook, fake_model([
        {"field": "tool", "value": "Insulation tester", "based_on": said},
        {"field": "duty", "value": "Wired and tested distribution panels", "based_on": said, "experience_id": exp_id},
        {"field": "summary", "value": "ITI electrician skilled in house wiring and motor repair.", "based_on": said},
    ]))
    assert result["added"] == 3 and not result["rejected"]
    assert len(notebook.suggested()) == 3
    assert "3 suggested lines to keep or remove" in notebook.export_blockers()


def test_drafted_lines_that_break_the_rules_are_dropped(notebook):
    said = "I fix motors, I do house wiring and panel wiring"
    result = draft_cv(notebook, fake_model([
        {"field": "certification", "value": "NCVT certificate", "based_on": said},       # facts can't be suggested
        {"field": "skill", "value": "Wired 50 houses", "based_on": said},                 # invented number
        {"field": "skill", "value": "Panel wiring", "based_on": "I worked at Tata Power"},  # not the student's words
        {"field": "tool", "value": "Megger", "based_on": said},                           # fine
    ]))
    assert result["added"] == 1
    assert len(result["rejected"]) == 3
    assert [f.value for f in notebook.suggested()] == ["Megger"]


def test_prompt_has_the_rules_the_saved_lines_and_the_transcript():
    nb = full_notebook()
    prompt = build_prompt(nb)
    assert "Never add an employer, certificate, grade, date or number" in prompt
    assert "KPTCL" in prompt and nb.values("experience")[0].id in prompt
    assert "Student: My name is Ravi Kumar" in prompt
