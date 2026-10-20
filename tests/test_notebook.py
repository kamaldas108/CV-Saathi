"""Notebook rules: no invention (F5), spelling (F4), checklist (F2), sensitive fields."""

from cvsaathi.notebook import CvNotebook


def nb_with(text: str) -> CvNotebook:
    nb = CvNotebook()
    nb.add_turn("student", text)
    return nb


# ----- no invention --------------------------------------------------------------------------


def test_transcription_markers_are_removed():
    # Seen live: "...Please tell me your name.<no speech>{pause}" showed in the chat.
    from cvsaathi.notebook import strip_markers

    assert strip_markers("Please tell me your name.<no speech>{pause}") == "Please tell me your name."
    assert strip_markers("[noise] My name is Ram") == "My name is Ram"
    nb = CvNotebook()
    nb.add_turn("agent", "<no speech>{pause}")
    assert nb.transcript == []  # nothing left to show


def test_evidence_must_be_something_the_student_said():
    nb = nb_with("My name is Ravi Kumar")
    result = nb.save_field("full_name", "Ravi Kumar", "I am Ravi Kumar from Mysuru")
    assert not result["ok"]
    assert nb.single("full_name") is None


def test_agent_turns_do_not_count_as_evidence():
    nb = CvNotebook()
    nb.add_turn("agent", "So you know AutoCAD?")
    assert not nb.save_field("skill", "AutoCAD", "you know AutoCAD")["ok"]


def test_numbers_must_come_from_the_student():
    nb = nb_with("I passed in 2024")
    assert not nb.save_field("passing_year", "2023", "I passed in 2024")["ok"]
    assert nb.save_field("passing_year", "2024", "I passed in 2024")["ok"]


def test_a_number_hidden_inside_the_phone_number_is_not_evidence():
    nb = nb_with("My number is 9845012345. I did house wiring.")
    said = nb.transcript[0]["text"]
    assert not nb.save_field("skill", "Wired 50 houses", said)["ok"]
    assert nb.save_field("phone", "9845012345", said)["ok"]


def test_rephrasing_is_allowed_but_adding_a_skill_is_not():
    nb = nb_with("I fix motors")
    assert nb.save_field("skill", "Repaired and serviced electric motors", "I fix motors")["ok"]
    rejected = nb.save_field("skill", "AutoCAD drafting", "I fix motors")
    assert not rejected["ok"]
    assert [f.value for f in nb.values("skill")] == ["Repaired and serviced electric motors"]


def test_invented_employer_is_rejected():
    nb = nb_with("I did apprenticeship as electrician for 1 year")
    result = nb.add_experience("Apprentice Electrician", "Tata Power", "1 year", "I did apprenticeship as electrician for 1 year")
    assert not result["ok"]


def test_kannada_and_hindi_digits_count_as_evidence():
    nb = nb_with("ನಾನು ೨೦೨೪ ರಲ್ಲಿ ಪಾಸ್ ಆದೆ")
    assert nb.save_field("passing_year", "2024", "೨೦೨೪ ರಲ್ಲಿ ಪಾಸ್ ಆದೆ")["ok"]
    nb = nb_with("मैंने २०२३ में पास किया")
    assert nb.save_field("passing_year", "2023", "२०२३ में पास किया")["ok"]


def test_spoken_phone_and_email_are_understood():
    nb = nb_with("my number is nine eight four five zero one two three double four and email ravi dot k at gmail dot com")
    said = nb.transcript[0]["text"]
    assert nb.save_field("phone", "9845012344", said)["ok"]
    assert nb.save_field("email", "ravi.k@gmail.com", said)["ok"]
    assert not nb.save_field("email", "ravi.kumar@gmail.com", said)["ok"]


# ----- sensitive fields ------------------------------------------------------------------------


def test_sensitive_fields_cannot_be_saved():
    nb = nb_with("I am Hindu, my caste is X, Aadhaar 1234 5678 9012, I am married")
    said = nb.transcript[0]["text"]
    assert not nb.save_field("caste", "X", said)["ok"]
    assert not nb.save_field("skill", "Hindu", said)["ok"]
    assert not nb.save_field("certification", "Aadhaar 1234 5678 9012", said)["ok"]
    assert not nb.save_field("project", "I am married", said)["ok"]
    assert nb.facts == []


# ----- spelling ----------------------------------------------------------------------------------


def test_names_need_spelling_confirmation_before_export(notebook):
    nb = nb_with("My name is Ravi Kumar")
    nb.save_field("full_name", "Ravi Kumar", "My name is Ravi Kumar")
    assert nb.single("full_name").status == "needs_spelling"
    assert any("Spelling of full name" in b for b in nb.export_blockers())


def test_saying_the_name_is_not_spelling_it():
    # Seen live: the model confirmed "Ram Kumar" using "My name is Ram Kumar" before any read-back.
    nb = nb_with("My name is Ram Kumar.")
    nb.save_field("full_name", "Ram Kumar", "My name is Ram Kumar")
    assert not nb.confirm_spelling("full_name", "Ram Kumar", "My name is Ram Kumar")["ok"]
    assert nb.single("full_name").status == "needs_spelling"


def test_confirmation_needs_the_students_yes_or_spelling():
    nb = nb_with("My name is Ravi Kumar")
    nb.save_field("full_name", "Ravi Kumar", "My name is Ravi Kumar")
    assert not nb.confirm_spelling("full_name", "Ravi Kumar", "the agent thinks so")["ok"]
    nb.add_turn("student", "haan sahi hai")
    assert nb.confirm_spelling("full_name", "Ravi Kumar", "haan sahi hai")["ok"]
    assert nb.single("full_name").status == "confirmed"


def test_spelled_correction_replaces_the_old_spelling_everywhere():
    nb = nb_with("I live in Mysore and studied at Government ITI Mysore")
    said = nb.transcript[0]["text"]
    nb.save_field("city", "Mysore", said)
    nb.save_field("institute", "Government ITI Mysore", said)
    nb.add_turn("student", "No, it is M Y S U R U")
    result = nb.confirm_spelling("city", "Mysuru", "M Y S U R U")
    assert result["ok"], result
    assert nb.single("city").value == "Mysuru"
    assert nb.single("institute").value == "Government ITI Mysuru"


def test_letter_by_letter_spelling_becomes_the_written_name():
    # Seen live: Gemini 3.8 Live passed spelled="R-A-V-I K-U-M-A-R".
    nb = nb_with("Hi, my name is Ravi Kumar.")
    nb.save_field("full_name", "Ravi Kumar", "my name is Ravi Kumar")
    nb.add_turn("student", "Yes, R-A-V-I K-U-M-A-R, that is correct.")
    assert nb.confirm_spelling("full_name", "R-A-V-I K-U-M-A-R", "R-A-V-I K-U-M-A-R")["ok"]
    assert nb.single("full_name").value == "Ravi Kumar"
    spaced = nb.confirm_spelling("full_name", "R A V I K U M A R", "R-A-V-I K-U-M-A-R")
    assert not spaced["ok"] and "written normally" in spaced["message"]
    assert nb.single("full_name").value == "Ravi Kumar"


def _ramanagar_conversation() -> CvNotebook:
    """From a live session: a partial correction, then yes to the agent's full read-back."""
    nb = CvNotebook()
    nb.add_turn("agent", "What is the name of your ITI or vocational institute?")
    nb.add_turn("student", "I did it from Ramnagar ITI.")
    assert nb.save_field("institute", "Ramnagar ITI", "I did it from Ramnagar ITI.")["ok"]
    nb.add_turn("agent", "Let me confirm the spelling. Is it R-A-M-N-A-G-A-R, I-T-I?")
    nb.add_turn("student", "No, Rama, R-A-M-A. Rest is okay.")
    nb.add_turn("agent", "Thank you. Just to confirm, is it spelled R-A-M-A-N-A-G-A-R, I-T-I?")
    nb.add_turn("student", "Yes, go ahead.")
    return nb


def test_yes_to_the_agents_corrected_read_back_confirms_the_new_spelling():
    nb = _ramanagar_conversation()
    result = nb.confirm_spelling("institute", "Ramanagar ITI", "Yes, go ahead.")
    assert result["ok"], result
    assert nb.single("institute").value == "Ramanagar ITI"
    assert nb.single("institute").status == "confirmed"


def test_yes_does_not_confirm_a_spelling_the_agent_never_read_back():
    nb = _ramanagar_conversation()
    assert not nb.confirm_spelling("institute", "Ramanagaram ITI", "Yes, go ahead.")["ok"]


def test_repeated_rejections_tell_the_agent_to_move_on():
    nb = _ramanagar_conversation()
    first = nb.confirm_spelling("institute", "Ramanagaram ITI", "Yes, go ahead.")
    second = nb.confirm_spelling("institute", "Ramanagaram ITI", "Yes, go ahead.")
    assert "Read the full spelling back once" in first["message"]
    assert "Move on to the next question" in second["message"]
    assert nb.single("institute").status == "needs_spelling"  # still blocks export
    assert any("Spelling of institute" in b for b in nb.export_blockers())


# ----- suggestions the student agrees to -----------------------------------------------------

SUGGESTION = "Plumbers often do pipe fitting, leak repair, bathroom fittings and drainage work. Which of these have you done?"


def test_yes_to_a_suggested_task_counts_as_evidence():
    nb = CvNotebook()
    nb.add_turn("agent", SUGGESTION)
    nb.add_turn("student", "Yes, I have done all of these.")
    assert nb.save_field("skill", "Leak repair", "Yes, I have done all of these")["ok"]
    assert nb.save_field("skill", "Drainage work", "Yes, I have done all of these")["ok"]


def test_a_suggestion_the_student_ruled_out_is_not_saved():
    nb = CvNotebook()
    nb.add_turn("agent", SUGGESTION)
    nb.add_turn("student", "Yes, pipe fitting and leak repair, but not drainage.")
    assert nb.save_field("skill", "Pipe fitting", "Yes, pipe fitting and leak repair")["ok"]
    rejected = nb.save_field("skill", "Drainage work", "Yes, pipe fitting and leak repair")
    assert not rejected["ok"] and "said no" in rejected["message"]


def test_yes_to_a_drafted_line_saves_that_line_only():
    nb = CvNotebook()
    nb.add_turn("student", "I worked at Urban Company. I was plumber. Last one year.")
    exp = nb.add_experience("Plumber", "Urban Company", "1 year", "I worked at Urban Company. I was plumber. Last one year.")
    assert exp["ok"], exp
    nb.add_turn("agent", "I'll write: Installed and repaired taps, sinks and toilets in customers' homes for Urban Company. Is that right?")
    nb.add_turn("student", "Haan, sahi hai.")
    line = "Installed and repaired taps, sinks and toilets in customers' homes for Urban Company"
    assert nb.add_duty(exp["experience_id"], line, "Haan, sahi hai")["ok"]
    other = nb.add_duty(exp["experience_id"], "Installed solar water heaters on rooftops", "Haan, sahi hai")
    assert not other["ok"]


def test_all_of_them_accepts_every_suggested_item():
    # Seen live: "All of them." was rejected, and the agent asked the same question three times.
    nb = CvNotebook()
    nb.add_turn("agent", "Which tools do you regularly use, like drills, testers, pliers, or multimeters?")
    nb.add_turn("student", "All of them.")
    for tool in ["Drill", "Tester", "Pliers", "Multimeter"]:
        assert nb.save_field("tool", tool, "All of them")["ok"], tool
    nb.add_turn("agent", "Do you use a megger and a clamp meter?")
    nb.add_turn("student", "Haan, dono. Sab.")
    assert nb.save_field("tool", "Clamp meter", "Sab")["ok"]


def test_list_words_with_a_no_do_not_count_as_agreement():
    nb = CvNotebook()
    nb.add_turn("agent", "Which tools do you use, like drills, testers, pliers, or multimeters?")
    nb.add_turn("student", "No, not all of them.")
    assert not nb.save_field("tool", "Multimeter", "not all of them")["ok"]
    # Spelling confirmation still needs a real yes, not a list word.
    nb.add_turn("student", "I studied at Ramnagar ITI")
    nb.save_field("institute", "Ramnagar ITI", "I studied at Ramnagar ITI")
    nb.add_turn("agent", "Is it R-A-M-N-A-G-A-R I-T-I?")
    nb.add_turn("student", "All.")
    assert not nb.confirm_spelling("institute", "Ramnagar ITI", "All")["ok"]


def test_yes_to_an_unrelated_question_is_not_evidence_for_a_new_skill():
    nb = CvNotebook()
    nb.add_turn("agent", "Is your mobile number 9898981234?")
    nb.add_turn("student", "Yes.")
    assert not nb.save_field("skill", "AutoCAD drafting", "Yes")["ok"]


# ----- draft CV: suggested lines ---------------------------------------------------------------


def test_suggested_lines_block_export_until_kept_or_removed(notebook):
    said = notebook.transcript[0]["text"]
    tool = notebook.suggest_line("tool", "Insulation tester", said)
    duty = notebook.suggest_line("duty", "Rewound and tested electric motors", said,
                                 notebook.values("experience")[0].id)
    assert tool["ok"] and duty["ok"], (tool, duty)
    assert "2 suggested lines to keep or remove" in notebook.export_blockers()
    assert not notebook.approve_review()["ok"]
    assert notebook.keep_line(tool["fact_id"])["ok"]
    assert notebook.get(tool["fact_id"]).source == "student_kept"
    assert notebook.remove(duty["fact_id"])["ok"]
    assert notebook.approve_review()["ok"]


def test_editing_a_suggestion_makes_it_the_students_line(notebook):
    s = notebook.suggest_line("skill", "Panel board wiring", notebook.transcript[0]["text"])
    assert notebook.student_edit(s["fact_id"], "Panel board wiring and testing")["ok"]
    assert notebook.get(s["fact_id"]).status == "draft"
    assert not notebook.suggested()


def test_suggestions_cannot_invent_facts_or_numbers(notebook):
    said = notebook.transcript[0]["text"]
    assert not notebook.suggest_line("certification", "NCVT certificate", said)["ok"]
    assert not notebook.suggest_line("skill", "Wired 50 houses", said)["ok"]
    assert not notebook.suggest_line("skill", "Panel wiring", "I worked for Tata Power")["ok"]  # not the student's words
    exp_id = notebook.values("experience")[0].id
    assert not notebook.suggest_line("duty", "Operated CNC lathes", said, exp_id)["ok"]  # does not grow from their words


def test_spelled_right_tap_confirms_a_name():
    nb = nb_with("My name is Ram Kumar")
    nb.save_field("full_name", "Ram Kumar", "My name is Ram Kumar")
    assert nb.keep_line(nb.single("full_name").id)["ok"]
    assert nb.single("full_name").status == "confirmed"


# ----- depth -------------------------------------------------------------------------------


def test_depth_hints_point_at_thin_sections_and_go_quiet_when_full(notebook):
    empty = CvNotebook()
    hints = " ".join(empty.depth_hints())
    assert "0 skill" in hints and "0 tool" in hints and "No projects" in hints
    full = " ".join(notebook.depth_hints())
    assert "skill(s)" not in full  # the fixture has 6 skills
    assert "No profile summary" in full  # basics are done, so a summary is suggested next


def test_spelled_acronym_keeps_its_saved_form():
    nb = nb_with("I was apprentice electrician at KPTCL")
    exp = nb.add_experience("Apprentice Electrician", "KPTCL", "", "apprentice electrician at KPTCL")
    nb.add_turn("student", "K-P-T-C-L")
    assert nb.confirm_spelling(exp["experience_id"], "K-P-T-C-L", "K-P-T-C-L")["ok"]
    assert nb.get(exp["experience_id"]).extra["employer"] == "KPTCL"


def test_confirming_a_different_spelling_without_spelling_it_is_rejected():
    nb = nb_with("I live in Mysore")
    nb.save_field("city", "Mysore", "I live in Mysore")
    nb.add_turn("student", "yes")
    assert not nb.confirm_spelling("city", "Mysuru", "yes")["ok"]


# ----- checklist, review ---------------------------------------------------------------------------


def test_checklist_lists_missing_required_fields():
    nb = nb_with("My name is Ravi")
    missing = {c["key"] for c in nb.checklist() if not c["done"]}
    assert missing == {"full_name", "contact", "city", "trade", "institute", "passing_year", "skill"}


def test_review_is_required_and_any_change_resets_it(notebook):
    assert notebook.export_blockers() == ["The student has not reviewed the full CV yet"]
    assert notebook.approve_review()["ok"]
    assert notebook.export_blockers() == []
    skill = notebook.values("skill")[0]
    assert notebook.student_edit(skill.id, "Motor rewinding")["ok"]
    assert notebook.export_blockers() == ["The student has not reviewed the full CV yet"]


def test_approve_is_refused_while_facts_are_missing():
    nb = nb_with("My name is Ravi")
    assert not nb.approve_review()["ok"]


def test_student_edit_of_a_name_confirms_it_and_replaces_everywhere(notebook):
    city = notebook.single("city")
    assert notebook.student_edit(city.id, "Mysore")["ok"]
    assert notebook.single("institute").value == "Government ITI Mysore"
    assert notebook.single("city").source == "student_edit"


# ----- seen live: a job described across turns, with plurals --------------------------------


def test_employer_name_matches_despite_plural():
    # Live log: "Working in urban companies since March 2026" was rejected for "Urban Company".
    nb = CvNotebook()
    nb.add_turn("student", "I am electrician.")
    nb.save_field("trade", "Electrician", "I am electrician")
    nb.add_turn("student", "Working in urban companies since March 2026.")
    result = nb.add_experience("Electrician", "Urban Company", "since March 2026",
                               "Working in urban companies since March 2026")
    assert result["ok"], result


def test_invented_employer_still_rejected():
    nb = CvNotebook()
    nb.add_turn("student", "Working in urban companies since March 2026.")
    assert not nb.add_experience("Electrician", "Tata Power", "", "Working in urban companies since March 2026")["ok"]


def test_role_from_an_unrelated_word_is_rejected():
    nb = CvNotebook()
    nb.add_turn("student", "Working in urban companies since March 2026.")
    assert not nb.add_experience("Site Supervisor", "Urban Company", "", "Working in urban companies since March 2026")["ok"]


def test_name_in_allows_inflections_only():
    from cvsaathi.notebook import name_in

    assert name_in("Urban Company", "working in urban companies")
    assert name_in("KPTCL", "K-P-T-C-L")
    assert not name_in("Urban Clap", "working in urban companies")
    assert not name_in("Larsen", "working in urban companies")


def test_markup_leaked_by_the_voice_model_is_removed():
    # Seen live in the cloud app: the agent's message contained "### Draft CV Creation <Step .../>".
    from cvsaathi.notebook import strip_markers

    leaked = ('Is there anything else you would like to add to your CV? ### Draft CV Creation '
              '<Step title="Writing your CV now [20s]" />\n<Step title="Tap Keep or Remove" />\n'
              "</Steps></LMDX>I'm writing your CV now.")
    assert strip_markers(leaked) == "Is there anything else you would like to add to your CV? I'm writing your CV now."
    assert strip_markers("Flat no 5 # main road") == "Flat no 5 # main road"
