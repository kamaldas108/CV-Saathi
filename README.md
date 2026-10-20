# CV-Saathi

A voice CV builder for ITI/VTI students. A student talks for about 10 minutes in English, Kannada or
Hindi and leaves with a one-page, ATS-friendly English CV as a PDF. Nothing goes on the CV that the
student did not say, and they check every line before export.

See [`specs/01-spec.md`](specs/01-spec.md) for the full spec.

## Run it

Needs Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn cvsaathi.server:app --port 8000
```

Open <http://localhost:8000>. (On macOS/Linux use `.venv/bin/python`.)

**Sample mode vs voice mode.** Without Google Cloud settings in `.env`, the app runs in *sample mode*:
a scripted text helper (not AI) asks the questions, and the badge says "Sample mode". To switch on the
Gemini Live voice interview on your Google Cloud credit, follow
[`docs/vertex-setup.md`](docs/vertex-setup.md).

## Test

```bash
.venv/Scripts/python -m pytest -q
```

The tests cover the rules (no invention, spelling, sensitive fields, checklist), design commands,
one-page PDF output for every template, and the full API flow in sample mode. Models are never called.

## How it works

```
browser (mic, 16 kHz PCM) ──ws──▶ server ──▶ Gemini Live (Vertex AI)
                                     ▲              │ tool calls: save_field, confirm_spelling, set_design…
                                     └── rules ◀────┘ accept or reject, with a reason
notebook ─▶ PDF (fpdf2, one A4 page) ─▶ preview PNG · download · share link · plain text
```

| Path | What it is |
|---|---|
| `cvsaathi/notebook.py` | CV facts and the rules: evidence, numbers, spelling, sensitive fields, checklist |
| `cvsaathi/design.py` | Templates, colours, fonts, section order, spacing; apply or refuse a change |
| `cvsaathi/render.py` | PDF, PNG preview and plain-text CV |
| `cvsaathi/live_tools.py` | Gemini Live prompt, tool declarations, tool dispatcher |
| `cvsaathi/server.py` | HTTP API, share links, Live WebSocket bridge |
| `cvsaathi/sample_interviewer.py` | Scripted text interviewer for sample mode |
| `web/` | The mobile web page |
| `docs/` | Decision record, build log, Vertex setup |
| `plan/` | Implementation plan with status and evidence |
