# Decision record

What was decided, what else was considered, and why.

## D1. Python (FastAPI) backend and a plain web page — 2026-10-20

- **Decided:** FastAPI server with the Google GenAI SDK; one HTML page, plain JavaScript, no build step.
- **Considered:** Node/TypeScript (as in AllPath).
- **Why:** the spec says the insurance-claim reference app "carries over almost unchanged", and that app
  is Python. A page without a build step stays light for budget phones on 3G/4G.

## D2. Sample mode until Vertex AI is set up — 2026-10-20

- **Decided:** with no `GOOGLE_CLOUD_PROJECT`, the server runs a scripted text interviewer (not AI) that
  writes through the same notebook rules as the voice model. The UI labels it "Sample mode".
- **Why:** the Cloud project was not set up yet. This lets the notebook, rules, templates, review and
  export be built, tested and demonstrated now. **A working screen in sample mode proves nothing about
  the voice model's behaviour** — that is what the evaluation set is for.

## D3. The voice model writes only through tools, and the rules check evidence — 2026-10-20

- **Decided:** every save carries `evidence`, the student's own words. The server accepts a fact only if:
  the evidence appears in a student turn of the transcript (agent turns don't count); every number in
  the value appears in the evidence (Kannada and Devanagari digits and English number words are
  normalised); emails match the spoken form; and, when the evidence is in English, the CV line shares at
  least one content word with it (allows rephrasing, blocks a new skill like "AutoCAD").
- **Limits, stated plainly:** with Kannada or Hindi evidence the content-word check is skipped (different
  script), so for those an added skill is caught only by the student's review and by the evaluation set.
  An English evidence quote that *mentions* a thing ("I never used AutoCAD") still contains the word, so
  the "invention pressure" case depends on the prompt — it is in the evaluation set for that reason.

## D4. Spelling: spelled out, or agreed to a read-back — 2026-10-20

- **Decided:** names (student, city, institute, employer) start as "needs spelling". `confirm_spelling`
  succeeds only if the student's words contain the letters of the spelling, or the spelling is unchanged
  and the student said yes (English, Hindi or Kannada yes-words). A changed spelling replaces the old
  one in every CV line. Export is blocked until all names are confirmed.
- **Why:** a model's "the student agreed" is not evidence; the student's transcript is.

## D5. One combined Live model for now; no separate Flash extraction step — 2026-10-20

- **Decided:** the Live model rephrases into CV English inside its tool calls. No ADK graph and no Flash
  model yet.
- **Considered:** the spec's cost control "keep the Live model on conversation only; do extraction and
  wording with the cheaper Flash model".
- **Why:** fewer moving parts to get the first pilot measured. The usage log (D8) will show whether the
  Live model's token use makes the split worth it. **This is a deviation from the spec's cost controls
  and should be revisited after the first pilot sessions.**

## D6. System prompt in English, replying in the student's language — 2026-10-20

- **Decided:** one English system prompt that tells the model to speak only English, Kannada or Hindi
  and reply in the student's language.
- **Considered:** the spec's "CV interviewer prompt in three languages".
- **Why:** native-audio models choose the output language themselves; one prompt is easier to keep
  consistent. The evaluation set's Kannada and Hindi cases will show whether this is enough.

## D7. PDF with fpdf2 core fonts; preview is the PDF itself — 2026-10-20

- **Decided:** fpdf2 draws the PDF; the preview and thumbnails are the same PDF rendered to PNG with
  pdfium. If content overflows, the layout shrinks in steps (down to 64%) until it fits one page.
- **Considered:** HTML templates + WeasyPrint (needs GTK on Windows), separate HTML preview.
- **Why:** pure-Python install, and the preview can never differ from the download. Core fonts cover
  Latin-1 only, which is enough because the CV is always English; other characters are transliterated.

## D8. Cost controls in code from day one — 2026-10-20

- 10-minute cap per voice connection and a 60-second silence timeout (both configurable).
- Context-window compression (sliding window) on the Live session.
- Token counts by modality written to `data/usage.jsonl` per session.

## D9. Photo (F8), 7-day drafts (F11) and retention deferred — 2026-10-20

- **Decided with the product owner:** first pass covers F1–F7, F9, F10 (and F12). Sessions and share links
  live in server memory: lost on restart, sessions dropped after 2 hours idle, share links expire after
  7 days. "Add my photo" is refused with an explanation until F8 lands.

## D10. Live model: Gemini 3.8 Live in us-central1 — 2026-10-20

- **Decided:** `gemini-3.8-live` on Vertex AI, region `us-central1`.
- **Checked:** a one-word Live session against project `cv-saathi` for each model and region:
  `gemini-3.8-live` and `gemini-live-2.5-flash-native-audio` work in `us-central1`; neither works in
  `asia-south1` (Mumbai) or `global`; `gemini-3.1-flash-live-preview` was not found under that ID in any
  of them. The app's real config (prompt, tools, compression) then ran against 3.8 Live: it called
  `save_field` and `confirm_spelling`, both passed the rules, and it spoke after each tool result.
- **Consequence (spec, Region):** no India region, so the consent text in all three languages now says
  voices are processed on Google servers in the USA.
- **Open:** 3.8 Live's price was not published when the spec was written. Watch `data/usage.jsonl` and
  Billing → Reports; switching to the older 2.5 native-audio model is a one-line `.env` change.
- **Found in that run:** the model passed the spelling as "R-A-V-I K-U-M-A-R". `confirm_spelling` now turns
  hyphenated letters into the written name, keeps the saved form when the letters match (so "KPTCL"
  stays "KPTCL"), and rejects spaced single letters.

## D11. Evidence across several answers; stop after two rejections — 2026-10-20

- **Seen live:** the job's company, role and duration came in three answers. A single quote could not
  cover them, every save was rejected, and the model kept asking the student to "say the exact phrase".
  Separately, a partial spelling correction ("Rama, R-A-M-A, rest is okay") followed by "yes" to the
  agent's full read-back was rejected, and the model asked the same spelling question about ten times.
- **Decided:** evidence may hold several quotes separated by `|`, each of which must be in a student turn.
  A yes confirms the exact spelling the agent read back in the turn just before it. A second rejection
  of the same save, or of the same spelling, tells the model to stop and move on; an unconfirmed name
  still blocks export and can be fixed by tapping it on the Check screen. The prompt forbids asking the
  student to repeat a sentence "for the system".

## D12. Depth: the agent suggests and drafts, the student confirms — 2026-10-20

- **Seen live:** a finished CV had 2 skills, no tools, no summary, and no job (lost to the loop in D11).
- **Product owner:** ITI/VTI students won't know what details belong on a CV; the agent should add
  detail and context, and the student corrects it.
- **Decided:**
  - The agent suggests typical tasks and tools for the student's trade and asks which they have done,
    and drafts fuller CV lines and reads them out. **A student's yes to the agent's turn just before it
    counts as evidence**, provided every content word of the saved line was in that agent turn or the
    student's words, and nothing the student put after "not/no" ("yes, but not drainage") is saved.
  - New sections: **Profile** (2-line summary from saved facts, read out and agreed) and **Tools and
    Equipment**. Descriptive skills render as bullets.
  - Each successful save returns the two thinnest parts of the CV (fewer than 6 skills, 4 tools, 3 duties
    per job, no projects, no certificates, no summary) for the agent to ask about next. Not required
    for export.
- **How this reads against F5:** "every CV line traces to something the student said" now includes an
  explicit yes to a line read to them. The risk is a student saying yes to everything; the Check screen
  and the evaluation set's "invention pressure" case are the guard. When the agent speaks Kannada or
  Hindi the word check can't compare scripts, so a yes there is accepted without it.

## D13. "Spelled out" means separate letters — 2026-10-20

- **Seen in a live replay:** the model saved "Ram Kumar" and confirmed it in the same turn, using
  "My name is Ram Kumar" as evidence, before reading it back. The old rule accepted any evidence whose
  letters contained the name, so saying the name counted as spelling it.
- **Decided:** a spelling is confirmed only by letters given one at a time in the student's words
  ("R-A-M K-U-M-A-R"), or by the student's yes to the agent's read-back of exactly that spelling. In sample
  mode a typed correction is saved as the student's own edit.

## D14. Short interview, then a drafted CV the student checks on screen — 2026-10-20

- **Product owner:** "get a few points, show the draft CV with the points understood, and ask to change
  at stage 2." Spoken back-and-forth for every detail was slow and still let drift through (live log:
  student said "maintain transformers", model saved "Installation of transformers" on a bare "Yes").
- **Decided:**
  - Steps are now **Talk → Check → Style → Design → Get CV**.
  - The interview collects the basics and a few points in the student's own words (about 5 minutes).
  - The model then drafts with a new tool, `suggest_line`: fuller skill and duty lines, typical skills and
    tools for the trade, a project line and a profile summary. Suggestions are stored with status
    "suggested", shown highlighted on the Check screen with **Keep / Fix / Remove**, and **block export
    until the student acts on each one**. A suggestion edited by the student becomes their own line.
  - Rules for suggestions: only skills, tools, duties, projects and the summary; never employers,
    certificates, dates or numbers; duties, projects and summary must share a content word with the
    student's words they're based on; `based_on` must be a real student quote.
  - Names are no longer spelled aloud during the interview. They show on the Check screen with a
    **"Spelled right"** button (a tap = the student's confirmation) and **Fix**.
- **How this reads against F5:** every line on the exported CV is either the student's own words
  (checked by the evidence rules) or a suggestion the student explicitly kept by tapping. This replaces
  D12's spoken-yes-to-a-draft as the main path for depth; the spoken path still works for voice changes.

## D15. Numbers must match whole numbers — 2026-10-20

- **Found while testing D14:** the number check joined all of the student's digits, so "50" counted as
  said because it appears inside the phone number 9845012345. Numbers now must appear as whole numbers;
  joining digits is allowed only for long numbers (6+ digits, e.g. a phone spoken digit by digit).

## D16. A stronger text model drafts the CV; the live model only talks — 2026-10-20

- **Product owner:** asked for a more advanced model to prevent the issues seen live.
- **Checked:** there is no newer Live (voice) model on the project than `gemini-3.8-live`. Text models
  listed on the project and answering: `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash`,
  `gemini-3.1-pro-preview`, `gemini-2.5-pro` — all through the `global` location only (404 in
  us-central1, except 2.5 Pro). On the same plumber interview both 3.8 Flash and 3.1 Pro kept "fixed" as
  "repaired", left out "drainage" (student said no), invented no employer/number, and marked their own
  additions; 3.1 Pro added more puffery ("proven ability to independently manage", "ensured clean
  workspaces"). 17.5 s vs 21.7 s.
- **Decided:** `gemini-3.8-flash` (generally available, plainer wording) drafts the whole CV in one call
  (`draft_cv`), triggered by the live model or a "Write my CV" button; it runs in the background so the
  conversation doesn't freeze. Every drafted line goes through `suggest_line` and shows as Suggested.
  This is the spec's original split (Live for conversation, a cheaper text model for wording) — it also
  resolves D5. Switch with `CVS_DRAFT_MODEL` in `.env`.
- **Consequence (spec, Region):** drafting runs in Google's `global` location, whose processing country
  isn't stated, so the consent text (3 languages) now says the draft is written on Google servers that may
  be outside India.

## D17. Final CV design: bigger text, fills the page, key facts, stars — 2026-10-20

- **Product owner:** bigger font, spaced to fill the page, more design, an infographic/table, bullets,
  language ratings with stars.
- **Decided:**
  - Text size: the largest of 130%…64% that fits on one page; then leftover space is spread between
    sections (up to 9 mm each), so a short CV fills the page.
  - A key-facts table under the name (Trade · ITI passed · Experience · Based in), only from saved facts.
  - Skills and tools in two bulleted columns when short; section markers per template.
  - Languages: five drawn stars **plus the level as text** ("Kannada ★★★★★ (Native)"), so ATS software
    still reads it. Levels come from the student (basic/good/fluent/native, asked in the interview); a
    language saved without a level shows no stars.
  - Still single column with selectable text, as F6 requires.
