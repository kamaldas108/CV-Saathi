"""The voice model's tools go through the same rules; bad calls never crash the session."""

from cvsaathi.live_tools import TOOL_NAMES, build_live_config, run_tool, tool_declarations
from cvsaathi.session import Session

from .conftest import full_notebook


def test_declared_tools_match_the_dispatcher():
    declared = [d.name for tool in tool_declarations() for d in tool.function_declarations]
    assert declared == TOOL_NAMES
    session = Session()
    for name in declared:
        assert run_tool(session, name, {})["message"] != f"Unknown tool '{name}'."


def test_live_config_builds_with_transcription_and_compression():
    config = build_live_config()
    assert config.input_audio_transcription is not None
    assert config.context_window_compression is not None
    assert "NO INVENTION" in config.system_instruction


def test_save_through_tool_needs_student_evidence():
    session = Session()
    session.notebook.add_turn("student", "I can do welding")
    assert not run_tool(session, "save_field", {"field": "skill", "value": "Arc welding", "evidence": "I am an expert welder"})["ok"]
    assert run_tool(session, "save_field", {"field": "skill", "value": "Arc welding", "evidence": "I can do welding"})["ok"]


def test_job_details_from_several_answers_can_be_saved():
    # From a live session: company, role and duration came in three different answers.
    session = Session()
    for text in ["I worked at Urban Company.", "I was plumber.", "Last one year."]:
        session.notebook.add_turn("student", text)
    result = run_tool(session, "add_experience", {
        "role": "Plumber", "employer": "Urban Company", "duration": "1 year",
        "evidence": "I worked at Urban Company | I was plumber | Last one year",
    })
    assert result["ok"], result


def test_one_made_up_quote_among_several_is_rejected():
    session = Session()
    for text in ["I worked at Urban Company.", "I was plumber."]:
        session.notebook.add_turn("student", text)
    result = run_tool(session, "add_experience", {
        "role": "Plumber", "employer": "Urban Company", "duration": "2 years",
        "evidence": "I worked at Urban Company | I was plumber | for two years",
    })
    assert not result["ok"]


def test_second_rejection_tells_the_model_to_move_on():
    session = Session()
    session.notebook.add_turn("student", "I was plumber.")
    args = {"role": "Plumber", "employer": "Urban Company", "duration": "1 year", "evidence": "the exact phrase"}
    first = run_tool(session, "add_experience", args)
    second = run_tool(session, "add_experience", args)
    assert "Skip this item" not in first["message"]
    assert "Skip this item for now" in second["message"]
    session.notebook.add_turn("student", "Urban Company, one year.")
    ok = run_tool(session, "add_experience", {**args, "evidence": "I was plumber | Urban Company, one year"})
    assert ok["ok"], ok
    assert "add_experience:" not in session.tool_failures  # a success resets the count


def test_set_design_tool_applies_and_refuses():
    session = Session()
    ok = run_tool(session, "set_design", {"accent_color": "blue", "template": None})
    assert ok["ok"] and session.design.accent == "blue"
    bad = run_tool(session, "set_design", {"accent_color": "gold"})
    assert not bad["ok"] and "gold" in bad["message"]


def test_go_to_export_is_blocked_until_review():
    session = Session()
    session.notebook = full_notebook()
    assert not run_tool(session, "go_to_step", {"step": "export"})["ok"]
    session.notebook.approve_review()
    assert run_tool(session, "go_to_step", {"step": "export"})["ok"]
    assert session.step == "export"


def test_draft_waits_for_the_whole_interview():
    # Seen live: the model drafted right after tools, before the job and languages.
    from cvsaathi.live_tools import draft_not_ready

    nb = full_notebook()
    assert "anything else" in draft_not_ready(nb)  # must ask before drafting
    nb.add_turn("agent", "Is there anything else you would like to add to your CV?")
    nb.add_turn("student", "No, that's all.")
    assert draft_not_ready(nb) is None
    nb.facts = [f for f in nb.facts if f.field != "language"]
    assert "languages" in draft_not_ready(nb)
    nb.facts = [f for f in nb.facts if f.field != "full_name"]
    assert "full name" in draft_not_ready(nb)


def test_draft_waits_until_work_experience_was_asked():
    # Seen live: a good session that never asked about a job or apprenticeship.
    from cvsaathi.live_tools import draft_not_ready

    nb = full_notebook()
    nb.facts = [f for f in nb.facts if f.field not in {"experience", "duty"}]
    assert "apprenticeship" in draft_not_ready(nb)
    nb.add_turn("student", "No, I have not done any job yet, I am a fresher.")
    assert not nb.mark_no_experience("I am a student")["ok"]  # not the student's words
    assert nb.mark_no_experience("I have not done any job yet")["ok"]
    nb.add_turn("agent", "Kuch aur add karna hai?")
    assert draft_not_ready(nb) is None


def test_no_experience_needs_the_student_to_say_so():
    nb = full_notebook()
    nb.facts = [f for f in nb.facts if f.field not in {"experience", "duty"}]
    nb.add_turn("student", "I like football.")
    assert not nb.mark_no_experience("I like football")["ok"]


def test_agent_cannot_skip_the_check_screen():
    # Seen live: the model moved to "choose a style" with 9 suggestions and 4 spellings pending.
    session = Session()
    session.notebook = full_notebook(confirm=False)
    blocked = run_tool(session, "go_to_step", {"step": "template"})
    assert not blocked["ok"] and "Check screen" in blocked["message"]
    session.notebook = full_notebook()
    assert run_tool(session, "go_to_step", {"step": "template"})["ok"]


def test_bad_arguments_and_unknown_tools_return_errors():
    session = Session()
    assert not run_tool(session, "save_field", {"field": None, "value": 42})["ok"]
    assert not run_tool(session, "draw_picture", {})["ok"]
    assert not run_tool(session, "add_duty", {"experience_id": "nope", "text": "x", "evidence": "x"})["ok"]


def test_get_notebook_returns_ids_and_blockers():
    session = Session()
    session.notebook = full_notebook()
    summary = run_tool(session, "get_notebook", {})
    assert summary["ok"]
    assert all("id" in line for line in summary["lines"])
    assert summary["blocking_export"] == ["The student has not reviewed the full CV yet"]


def test_a_dead_draft_does_not_block_write_my_cv():
    # Seen live: the drafting task died, the flag stayed on, and "Write my CV" kept saying
    # "already being written" for minutes.
    import asyncio

    from cvsaathi.server import drafting_now

    session = Session()
    assert not drafting_now(session)

    async def finished():
        return None

    async def check():
        session.drafting = True  # the stuck flag
        session.draft_task = asyncio.ensure_future(finished())
        await session.draft_task
        return drafting_now(session)

    assert asyncio.run(check()) is False


def test_city_is_asked_before_drafting():
    from cvsaathi.live_tools import draft_not_ready

    nb = full_notebook()
    nb.facts = [f for f in nb.facts if f.field != "city"]
    assert "city" in draft_not_ready(nb)


def test_failed_job_saves_do_not_block_drafting_forever():
    # Live: every add_experience was rejected, the gate kept saying "ask about work",
    # and the agent asked the student to say they had no job.
    from cvsaathi.live_tools import draft_not_ready

    nb = full_notebook()
    nb.facts = [f for f in nb.facts if f.field not in {"experience", "duty"}]
    nb.add_turn("agent", "Anything else to add?")
    assert "apprenticeship" in draft_not_ready(nb)
    nb.add_experience("Electrician", "Nowhere Ltd", "", "I fix motors")
    nb.add_experience("Electrician", "Nowhere Ltd", "", "I fix motors")
    assert draft_not_ready(nb) is None
