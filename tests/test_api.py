"""End-to-end through the HTTP API in sample mode: interview, design, review, export, share, start over."""

import pytest
from fastapi.testclient import TestClient

from cvsaathi import server
from cvsaathi.render import pdf_page_count, pdf_text

ANSWERS = [
    "My name is ravi kumar",
    "yes",
    "98450 12345",
    "ravi.k@gmail.com",
    "Mysore",
    "Mysuru",  # corrects the spelling
    "electrician",
    "Government ITI Mysuru",
    "yes",
    "2024",
    "house wiring, motor rewinding, panel wiring",
    "multimeter, megger, drill machine",
    "Apprentice Electrician, KPTCL, 1 year",
    "yes",
    "repaired electric motors, did house wiring",
    "no",
    "Kannada, Hindi, English",
]


@pytest.fixture
def client():
    server.sessions.clear()
    server.shares.clear()
    return TestClient(server.app)


def start(client):
    res = client.post("/api/sessions", json={"consent": True, "adult": True})
    assert res.status_code == 200, res.text
    return res.json()


def interview(client, sid):
    state = None
    for answer in ANSWERS:
        res = client.post(f"/api/sessions/{sid}/message", json={"text": answer})
        assert res.status_code == 200, res.text
        state = res.json()["state"]
    return state


def test_consent_and_age_are_required(client):
    assert client.post("/api/sessions", json={"consent": False, "adult": True}).status_code == 400
    assert client.post("/api/sessions", json={"consent": True, "adult": False}).status_code == 403


def test_sessions_belong_to_their_browser(client):
    sid = start(client)["session_id"]
    other = TestClient(server.app)
    assert other.get(f"/api/sessions/{sid}").status_code == 404


def test_full_sample_flow_to_one_page_pdf(client):
    state = start(client)
    sid = state["session_id"]
    assert state["mode"] == "sample"
    state = interview(client, sid)
    nb = state["notebook"]
    assert all(item["done"] for item in nb["checklist"])
    assert nb["unconfirmed_spellings"] == []
    assert state["step"] == "review"  # the draft CV is checked right after the interview
    values = {f["field"]: f["value"] for f in nb["facts"]}
    assert values["city"] == "Mysuru"
    assert values["full_name"] == "Ravi Kumar"

    # Export is blocked until the student has reviewed every line (F9).
    assert client.get(f"/api/sessions/{sid}/cv.pdf").status_code == 409
    assert client.post(f"/api/sessions/{sid}/step", json={"step": "export"}).status_code == 409

    # Template pick and voice-style design commands (F6, F7).
    client.post(f"/api/sessions/{sid}/design", json={"changes": {"template": "modern"}})
    reply = client.post(f"/api/sessions/{sid}/message", json={"text": "make it teal and put skills above experience"}).json()
    assert reply["state"]["design"]["accent"] == "teal"
    order = reply["state"]["design"]["section_order"]
    assert order.index("skills") == order.index("experience") - 1
    refused = client.post(f"/api/sessions/{sid}/message", json={"text": "add a logo with animation"}).json()
    assert "can't" in refused["reply"]

    preview = client.get(f"/api/sessions/{sid}/preview.png?template=bold&w=240")
    assert preview.status_code == 200 and preview.content[:4] == b"\x89PNG"

    # Review: tap-edit a line, then approve.
    skill = next(f for f in reply["state"]["notebook"]["facts"] if f["field"] == "skill")
    edited = client.patch(f"/api/sessions/{sid}/lines/{skill['id']}", json={"value": "Domestic house wiring"})
    assert edited.status_code == 200
    assert client.post(f"/api/sessions/{sid}/approve").json()["step"] == "template"

    pdf = client.get(f"/api/sessions/{sid}/cv.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "Ravi_Kumar_CV.pdf" in pdf.headers["content-disposition"]
    assert pdf_page_count(pdf.content) == 1
    assert "Domestic house wiring" in pdf_text(pdf.content)

    text = client.get(f"/api/sessions/{sid}/cv.txt").text
    assert "Ravi Kumar" in text and "KPTCL" in text


def test_keep_and_remove_suggested_lines_through_the_api(client):
    sid = start(client)["session_id"]
    interview(client, sid)
    session = server.sessions[sid]
    said = next(t["text"] for t in session.notebook.transcript if t["speaker"] == "student" and "wiring" in t["text"])
    keep = session.notebook.suggest_line("skill", "Domestic wiring and fault finding", said)["fact_id"]
    drop = session.notebook.suggest_line("tool", "Clamp meter", said)["fact_id"]
    assert client.post(f"/api/sessions/{sid}/approve").status_code == 409  # suggestions pending
    client.post(f"/api/sessions/{sid}/lines/{keep}/keep")
    client.delete(f"/api/sessions/{sid}/lines/{drop}")
    assert client.post(f"/api/sessions/{sid}/approve").json()["step"] == "template"
    text = client.get(f"/api/sessions/{sid}/cv.txt").text
    assert "Domestic wiring and fault finding" in text and "Clamp meter" not in text


def test_share_link_opens_pdf_and_dies_on_start_over(client):
    sid = start(client)["session_id"]
    interview(client, sid)
    assert client.post(f"/api/sessions/{sid}/share").status_code == 409  # not reviewed yet
    client.post(f"/api/sessions/{sid}/approve")
    url = client.post(f"/api/sessions/{sid}/share").json()["url"]
    path = url.split("testserver")[-1]
    assert len(path.split("/s/")[1]) >= 30
    shared = client.get(path)
    assert shared.status_code == 200
    assert shared.headers["x-robots-tag"].startswith("noindex")
    assert pdf_page_count(shared.content) == 1

    state = client.post(f"/api/sessions/{sid}/reset").json()
    assert state["notebook"]["facts"] == []
    assert state["step"] == "interview"
    assert client.get(path).status_code == 404


def test_share_link_expires_after_seven_days(client, monkeypatch):
    sid = start(client)["session_id"]
    interview(client, sid)
    client.post(f"/api/sessions/{sid}/approve")
    path = "/s/" + client.post(f"/api/sessions/{sid}/share").json()["url"].split("/s/")[1]
    real_time = server.time.time
    monkeypatch.setattr(server.time, "time", lambda: real_time() + 7 * 24 * 3600 + 1)
    assert client.get(path).status_code == 404


def test_rejected_answer_is_explained_and_asked_again(client):
    sid = start(client)["session_id"]
    client.post(f"/api/sessions/{sid}/message", json={"text": "ravi kumar"})
    client.post(f"/api/sessions/{sid}/message", json={"text": "yes"})
    reply = client.post(f"/api/sessions/{sid}/message", json={"text": "12345"}).json()
    assert "10 digits" in reply["reply"]
    assert not any(f["field"] == "phone" for f in reply["state"]["notebook"]["facts"])


def test_yes_is_not_accepted_as_an_answer_to_an_open_question(client):
    sid = start(client)["session_id"]
    for text in ["ravi kumar", "yes", "9845012345", "no", "Mysuru", "yes"]:
        client.post(f"/api/sessions/{sid}/message", json={"text": text})
    reply = client.post(f"/api/sessions/{sid}/message", json={"text": "yes"}).json()
    assert "Please type your answer" in reply["reply"]
    assert not any(f["field"] == "trade" for f in reply["state"]["notebook"]["facts"])


def test_sensitive_answer_stays_off_the_cv(client):
    sid = start(client)["session_id"]
    for text in ["ravi kumar", "yes", "9845012345", "no", "Mysuru", "yes", "electrician", "ITI Mysuru", "yes", "2024"]:
        client.post(f"/api/sessions/{sid}/message", json={"text": text})
    reply = client.post(f"/api/sessions/{sid}/message", json={"text": "wiring, I am Hindu, caste OBC"}).json()
    skills = [f["value"] for f in reply["state"]["notebook"]["facts"] if f["field"] == "skill"]
    assert skills == ["Wiring"]
