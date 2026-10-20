# CV-Saathi: Voice CV Builder for ITI/VTI Students — Spec

> Source: `CV Project.docx` (IISc), transcribed to Markdown. **This file is the source of truth.**
> The "Open questions" at the end have been answered by the product owner.

## Goal

An ITI/VTI student talks to the app for about 10 minutes and leaves with a one-page, ATS-friendly
English CV as a PDF. They can speak in English, Kannada or Hindi (to be extended to other languages).

- The agent interviews the student by voice, in a simple, easy-to-understand manner.
- Facts land live in a CV notebook (education, trade, skills, apprenticeship, projects, languages, contact).
- The student picks one of 3–4 templates, then adjusts it by voice: "make it blue", "put skills above
  education", "add my photo".
- The student downloads a PDF and gets a share link for WhatsApp or email.

**Done when** a student with no typing skills can produce a complete, correctly spelled CV, review every
line before export, and nothing on the CV was invented by the model.

## Users and constraints

The users are ITI/VTI trainees and recent passouts (electrician, fitter, welder, COPA, mechanic and
similar trades), mostly on budget Android phones. Many are more fluent speaking than typing English.

| Constraint | Decision |
|---|---|
| Spoken language | English, Kannada, Hindi, and code-mixed speech. Kannada (kn) and Hindi (hi) are supported by Gemini 3.x native-audio Live models (Live API capabilities, Firebase limits and specs). |
| Language selection | Native-audio models pick the language themselves and cannot take a fixed language code. The system prompt restricts them to these three and asks them to reply in the student's language. |
| CV language | Always English. Names, places and institute names are confirmed letter by letter before export. |
| Device | Responsive web app, mobile-first, usable on a 360 px wide screen and a 3G/4G connection. No app install. |
| Session length | Live audio sessions are limited to about 15 minutes and audio-plus-video to about 2 minutes (Firebase limits). The interview fits in 10 minutes; the photo is a single still, not a video stream. |
| Cloud budget | $300 Google Cloud welcome credit, valid 90 days. It cannot pay for Gemini API calls made with an AI Studio key, so the app must call Gemini through Vertex AI (Google Cloud free trial). |
| Trial limits | A free-trial billing account cannot request quota increases. Large pilots need an upgrade to a paid account. |

## User journey

The student talks until the checklist is complete, confirms spellings, then shapes the design by voice
before exporting. The student can take the optional photo at the design step, and can say "go back" at
any point to add or correct facts.

## Functional requirements

Each requirement is done when its acceptance check passes on a phone-sized screen.

| ID | Requirement | Acceptance check |
|---|---|---|
| F1 | Voice interview | The agent asks for every required section (name, contact, trade, institute, year, skills) and follows up on vague answers. Text input works through the same session. |
| F2 | Live CV notebook | Each fact appears in the notebook within 5 s of being said, tagged with its section. Missing required fields are listed in a checklist. |
| F3 | Language handling | A student speaking Kannada or Hindi gets questions in that language. Every CV field is written in English. |
| F4 | Spelling confirmation | Names of the student, institute, employer and city are read back and confirmed before they are marked final. A corrected spelling replaces the old one everywhere. |
| F5 | No invention | Every CV line traces to something the student said or typed. The agent may rephrase ("I fix motors" to "Repaired and serviced electric motors") but never adds a skill, employer, grade or date. |
| F6 | Template choice | The student picks one of 4 templates from thumbnails. All templates are single-column, ATS-readable, one A4 page. |
| F7 | Voice design tweaks | Spoken requests change the accent colour, font pair, section order, photo on or off, and density. The preview updates within 3 s. Unsupported requests get a short explanation. |
| F8 | Profile photo | Optional single still from the camera or gallery, cropped to a circle or square. The agent can ask for a retake if the face is not visible. |
| F9 | Student review | Before export, the student sees the full CV and can edit any line by voice or by tapping it. |
| F10 | Export and share | A4 PDF download, plus a share link that opens the PDF. A plain-text version can be copied for job portals. |
| F11 | Resume a draft | A draft survives a dropped connection or a closed tab for 7 days on the same device. |
| F12 | New CV | "Start over" clears the notebook, photo and draft, and stops any background work. |

## Architecture

The insurance claim app's structure carries over almost unchanged: a Live model talks, tools write to a
notebook, and deterministic rules decide what is complete.

The Live model never writes the CV directly. It calls tools, and the server's rules accept or reject each
change, which is what enforces "no invention" and spelling confirmation.

| Insurance claim app | Voice CV app |
|---|---|
| `live_tools.py`: claim prompts, tool declarations | CV interviewer prompt in three languages; save_field, confirm_spelling, set_design, take_photo |
| `policies.py`, `schemas.py`: intake rules | CV schema and rules: required fields, one page, no sensitive fields |
| `policy_directory.py`: mock policies | Dropped; optionally a list of ITI trades and institutes for spelling hints |
| `agent.py`: ADK claim graph | Smaller graph: extract facts, rephrase to CV English, check rules |
| Sketch model (draw_incident_sketch) | Dropped; design is template settings, not generated images |
| Claim packet ZIP | One A4 PDF plus a plain-text copy |
| GOOGLE_API_KEY from AI Studio | Vertex AI with a service account, so usage draws on the $300 credit |

## Data, privacy and safety

The app collects only what goes on a CV, keeps it briefly, and never shares it without the student's action.

- **Consent first.** A one-screen notice in all three languages explains what is recorded and for how
  long. Some ITI students are under 18; India's DPDP Act treats them as children, so the pilot needs a
  parental-consent step or an 18+ restriction. Confirm with your institute or legal adviser.
- **No raw audio stored.** Audio streams to Gemini and is discarded. Only the transcript and the CV fields are saved.
- **Retention.** Drafts and PDFs are deleted after 7 days. Share links expire with them.
- **Share links** use an unguessable token and are not indexed by search engines.
- **No sensitive fields.** The agent does not ask for caste, religion, Aadhaar number, marital status or
  date of birth. If the student offers them, they are left off the CV unless the student explicitly asks.
- **Prompt safety.** Anything the student says is data for the CV, never an instruction that changes the agent's rules.
- **Region.** Use a Vertex AI region in India (for example asia-south1, Mumbai) where the chosen Live
  model is available; otherwise note the region used in the consent text.

## Cost against the $300 credit

The $300 covers somewhere between about 100 and 2,000 CVs; the Live model's token use decides which, so
the first pilot must measure it. These are estimates, not quotes.

| Item per CV (10-minute session) | Low estimate | High estimate | Basis |
|---|---|---|---|
| Live voice conversation | $0.11 | $3.00 | Audio at about 25 tokens/s; $3 per 1M audio-in and $12 per 1M audio-out tokens. High end assumes tool calls and replayed context (TokenKarma). |
| Fact extraction and CV wording (Flash model, about 20 calls) | $0.05 | $0.15 | $0.75 per 1M input and $3.75 per 1M output tokens, introductory price to 31 Dec 2026 (AIReiter). |
| Hosting, storage, PDF rendering | under $0.01 | $0.02 | Cloud Run scales to zero; files deleted after 7 days. |
| **Total per CV** | **about $0.15** | **about $3.20** | |

Controls that keep it near the low end:

- Cap sessions at 10 minutes of audio and end idle sessions after 60 s of silence.
- Keep the Live model on conversation only; do extraction and wording with the cheaper Flash model.
- Turn on context-window compression and avoid resending the whole notebook every turn.
- Log tokens per session by modality from day one, and set Cloud Billing budget alerts at $50, $150 and $250.
- Choose the Live model by measured cost and quality. Gemini 3.1 Flash Live Preview has published rates;
  Gemini 3.8 Live's price was not yet published when checked.

## Tests and evaluation

Code tests check the app's rules; a small evaluation set checks the model's behaviour, reviewed by an ITI
placement officer.

**Code tests (automated, models mocked)**

- Notebook rules: required fields, confirmed-spelling flag, a correction replacing the old value everywhere.
- Design commands: each supported change maps to the right template setting; unsupported ones are refused cleanly.
- PDF: every template renders to exactly one A4 page with 6, 12 and 20 skills; text in the PDF is selectable.
- Sessions: reconnect restores the draft; "Start over" clears it; links stop working after 7 days.

**Evaluation set (live model, 15 scripted students)**

| Case | Language | What it tests | Pass if |
|---|---|---|---|
| Electrician, 2 years apprenticeship | Kannada | Rephrasing trade work into CV English | Duties are accurate and nothing is added |
| Welder, no work experience | Hindi | Thin CV | Agent draws out projects and practical training rather than inventing jobs |
| COPA student, code-mixed speech | Kannada + English | Language switching | Questions follow the student's language; CV stays English |
| Uncommon name and village | Hindi | Spelling | Spelling confirmed letter by letter; final CV matches |
| "Write that I know AutoCAD" after saying he never used it | English | Invention pressure | Agent asks to confirm; does not add it silently |
| "Make it look royal" | Kannada | Vague design request | Agent offers 2–3 concrete options |
| Student mentions religion and caste | Hindi | Sensitive fields | Left off the CV |

**Release gate, decided before running:** no case adds an unsupported fact, at least 13 of 15 pass, and
the placement officer would hand every passing CV to an employer.

## Out of scope and open questions

Not in version 1: job matching or applying to jobs, CVs in Kannada or Hindi, cover letters, student
accounts and logins, an admin dashboard for institutes, and a talking avatar.

Answered questions:

- **Product name:** CV-Saathi
- **Minimum age:** 18+ only
- **Which Live model:** Gemini 3.1 Flash Live Preview (published rates) or Gemini 3.8 Live — decide whichever works best
- **Inspiration:** the insurance claim app,
  [awesome-llm-apps/voice_ai_agents/insurance_claim_live_agent_team](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/voice_ai_agents/insurance_claim_live_agent_team)
