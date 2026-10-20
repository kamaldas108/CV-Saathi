"""Design commands (F7): each supported change maps to the right setting; others are refused."""

import pytest

from cvsaathi.design import SECTIONS, DesignSettings, apply_changes, parse_request


@pytest.mark.parametrize("text, expected", [
    ("make it blue", {"accent_color": "blue"}),
    ("Make it RED please", {"accent_color": "maroon"}),
    ("use a formal font", {"font_pair": "serif"}),
    ("simple font", {"font_pair": "sans"}),
    ("put skills above education", {"move_section": "skills", "place": "above", "relative_to": "education"}),
    ("move education to the top", {"move_section": "education", "place": "top"}),
    ("languages last", {"move_section": "languages", "place": "bottom"}),
    ("make it compact", {"density": "compact"}),
    ("use the bold template", {"template": "bold"}),
    ("add my photo", {"photo": True}),
    ("remove the photo", {"photo": False}),
])
def test_phrases_map_to_settings(text, expected):
    assert parse_request(text)["changes"] == expected


def test_vague_request_offers_concrete_options():
    parsed = parse_request("make it look royal")
    assert parsed.get("vague")
    assert 2 <= len(parsed["options"]) <= 3


def test_unsupported_request_is_refused_with_a_short_explanation():
    parsed = parse_request("add a logo with animation")
    assert parsed.get("unsupported")
    assert "colour" in parsed["message"]


def test_apply_changes_updates_settings():
    s = DesignSettings()
    result = apply_changes(s, {"accent_color": "teal", "move_section": "skills", "place": "above", "relative_to": "experience"})
    assert result["ok"]
    assert s.accent == "teal"
    assert s.section_order.index("skills") == s.section_order.index("experience") - 1
    assert sorted(s.section_order) == sorted(SECTIONS)


def test_below_and_bottom_moves():
    s = DesignSettings()
    apply_changes(s, {"move_section": "experience", "place": "below", "relative_to": "education"})
    assert s.section_order.index("experience") == s.section_order.index("education") + 1
    apply_changes(s, {"move_section": "skills", "place": "bottom"})
    assert s.section_order[-1] == "skills"


@pytest.mark.parametrize("changes", [
    {"accent_color": "rainbow"},
    {"font_pair": "comic"},
    {"template": "two-column"},
    {"move_section": "hobbies", "place": "top"},
    {"move_section": "skills", "place": "above", "relative_to": "skills"},
    {"density": "huge"},
    {"photo": True},  # no photo exists yet
    {},
])
def test_unsupported_changes_are_refused_and_leave_settings_alone(changes):
    s = DesignSettings()
    before = s.to_dict()
    result = apply_changes(s, changes, has_photo=False)
    assert not result["ok"]
    assert result["refused"]
    assert s.to_dict() == before
