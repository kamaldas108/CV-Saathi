# CV-Saathi — notes for the coding tool

**What this is.** A voice CV builder for ITI/VTI students: Gemini Live interviews the student, tools
write to a CV notebook, deterministic rules accept or reject every change, and the app renders a
one-page A4 PDF.

**Where the written decisions live.**
- `specs/01-spec.md` — what the app must do. **This is the source of truth.**
- `plan/implementation-plan.md` — tasks, status and completion evidence.
- `docs/decision-record.md` — what was decided, alternatives, and why.
- `docs/build-log.md` — one line per change, with the requirement it serves.
- `docs/vertex-setup.md` — switching on the voice model.

**How to run things.** `.venv/Scripts/python -m uvicorn cvsaathi.server:app --port 8000` ·
`.venv/Scripts/python -m pytest -q`. Without `GOOGLE_CLOUD_PROJECT` in `.env` the server runs in sample
mode (scripted text, not AI), which is labelled in the UI — a working screen there proves nothing about
the voice model.

**`.env` and any service-account key are gitignored and must stay that way.**

**The rules are the product.** The voice model must never write the CV except through `run_tool` →
`CvNotebook`. Don't add a path that bypasses the evidence, spelling or sensitive-field checks.

**Before saying a task is finished,** state which acceptance criteria now pass and how to check them
independently. A passing suite counts only once breaking the rule on purpose has been shown to fail it.
