# Implementation plan

Each task lists the spec requirement, its acceptance criteria, and the evidence that it is done.
"Sample mode" evidence shows the app and its rules work; it says nothing about the voice model.

## Pass 1 — working core (2026-10-20)

| Task | Req | Status | Evidence |
|---|---|---|---|
| Notebook + rules: required fields, checklist, evidence check, numbers, sensitive fields | F2, F5, privacy | Done | `tests/test_notebook.py`; disabling the evidence check or the sensitive filter fails the suite |
| Spelling confirmation, replace everywhere, export blocked until confirmed | F4 | Done | `tests/test_notebook.py` spelling tests; disabling either rule fails the suite |
| Live model wiring: prompt, tools, dispatcher, transcripts, audio, 10-min cap, 60-s idle, compression, usage log | F1, F3 | Built; tools verified against gemini-3.8-live by text (D10). **Not yet tried by voice in the browser** | `tests/test_live_tools.py` (config builds, tools route through rules). Needs `docs/vertex-setup.md` then a real session |
| Sample-mode text interviewer | F1 (text path) | Done | `tests/test_api.py::test_full_sample_flow_to_one_page_pdf`; clicked through at 360 px |
| 4 single-column templates, thumbnails, one A4 page, selectable text | F6 | Done | `tests/test_render.py` (4 templates × 6/12/20 skills × 2 densities); disabling shrink-to-fit fails it |
| Design changes: colour, font, order, density, template, photo; vague → options; unsupported → explanation | F7 | Done (photo refused until F8) | `tests/test_design.py`; preview re-renders per request |
| Review: tap to edit or remove any line; approve; any change needs re-approval | F9 | Done (tap). Voice edits via the Live tools, untested live | `tests/test_notebook.py::test_review_is_required_and_any_change_resets_it`; clicked through |
| PDF download, share link (unguessable, noindex, 7 days), plain-text copy | F10 | Done (links in memory) | `tests/test_api.py` share tests; disabling expiry fails the suite |
| Start over clears notebook, design, share links, live connection | F12 | Done (no photo/draft to clear yet) | `tests/test_api.py::test_share_link_opens_pdf_and_dies_on_start_over` |
| Consent screen in 3 languages, 18+ gate | Privacy | Done; **Hindi/Kannada text needs a native speaker's check** | `tests/test_api.py::test_consent_and_age_are_required` |

## Pass 2 — next

| Task | Req | Notes |
|---|---|---|
| Set up Vertex AI and run a real voice session; fix what breaks | F1, F3 | Follow `docs/vertex-setup.md`. Check F2's "within 5 s" and F7's "within 3 s" live. |
| Profile photo: camera/gallery still, crop circle/square, retake prompt | F8 | Needs a photo slot in templates and `take_photo` tool |
| Drafts that survive 7 days on the same device; store PDFs/links outside memory; delete after 7 days | F11, retention | Needs storage (e.g. Firestore/Cloud Storage with TTL) |
| Evaluation harness for the 15 scripted students, with the placement officer | Eval | Release gate: no added facts, ≥ 13/15 pass |
| HTTPS deployment (Cloud Run, India region if the model is there) | Device | Needed for the microphone on phones |
| Revisit D5 (Flash extraction) using measured token costs | Cost | `data/usage.jsonl` |
