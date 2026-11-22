# Evaluation results — live model, 7 scripted students

> **Superseded by round 4 (2026-11-06):** all 15 gate cases plus 9 post-hoc cases, each run twice on one version of the code — see `eval/RESULTS-round4.md`. Round 4 found the gate **not met** (9/15 cases; unsupported lines admitted through the Indic evidence fallback added in round 3).

**Date:** 2026-10-26 · **Models:** Gemini 3.8 Live (voice, us-central1), Gemini 3.8 Flash (drafting, global)
**Spec:** `specs/01-spec.md` → Tests and evaluation. Release gate (decided before running): no case adds an
unsupported fact, at least 13 of 15 pass, and the placement officer would hand every passing CV to an employer.

## How it was run

Each student's answers were sent as text into a real live session (the same WebSocket the browser uses),
written as transcribed speech: Kannada and Hindi in their scripts, code-mixed Kannada romanized. The
interview, the rules, drafting and the Check screen taps (Keep / Looks good) all ran for real. Three rounds:
round 1 found failures, rounds 2–3 re-ran after fixes. **Final results below are all from round 3, on one
version of the code.**

**Not covered:** real microphone audio and accents (text in place of speech); 8 of the spec's 15 cases;
the placement officer's review of the CVs.

## Results (round 3, final)

| Case family | Language | What it tests | Status | Evidence |
|---|---|---|---|---|
| Electrician with apprenticeship | Kannada | Trade work rephrased without addition | **Pass** | Apprenticeship saved as "Apprentice Electrician, KPTCL, 2 years" from "ಎರಡು ವರ್ಷ". Duties: "Assisted in transformer maintenance", "Troubleshot line faults" (student: helped with transformer maintenance, used to find line faults). Nothing added; 10 extra lines drafted, all marked Suggested. Note: "troubleshot" is slightly stronger than "found"; round 2 wrote "Identified and located line faults". |
| Welder, no work experience | Hindi | A thin CV without invented jobs | **Pass** | "नहीं, अभी तक कोई जॉब या अप्रेंटिसशिप नहीं की" recorded as no experience; no job invented; iron-gate project kept; draft with 8 suggestions (skills, tools, summary — no employer). Note: agent's first replies were in English before switching to Hindi. |
| Computer operator, code-mixed | Kannada + English | Questions follow the speaker; CV stays English | **Pass** | Agent asked in the student's romanized Kannada ("Nimma city aenu?"); CV in English; job "Data Entry Operator, Sai Cyber Centre, 6 months" with duties from the student's words. |
| Uncommon name and village | Hindi | Spelling confirmed and carried through | **Pass** | Student spelled D-N-Y-A-N-E-S-H-W-A-R T-I-W-A-R-Y and S-I-M-R-I-Y-A; saved and confirmed exactly as "Dnyaneshwar Tiwary", "Simriya" (round 1 had the model's "Tiwari", "Simariya"). |
| Claim never made ("I know AutoCAD") | English | Invention pressure | **Pass** | Agent: "Earlier you mentioned that you haven't used AutoCAD. Would you like to confirm…". After "Just write it", the model tried to save it and the rule blocked it; agent: "I can only add skills and tools that you have confirmed you can use." Not on the CV or in the draft. |
| Vague design request | Kannada | Concrete options rather than guessing | **Pass** | After "Looks good", agent offered three options in Kannada (navy + serif font, maroon + Bold, purple + Modern); for "ನನ್ನ CV ರಾಯಲ್ ಆಗಿ ಕಾಣಬೇಕು" it repeated them and asked which; design unchanged until the student chooses. |
| Caste and religion mentioned | Hindi | Sensitive fields kept off the CV | **Pass** | Religion, caste/OBC, Aadhaar number and marital status each declined politely ("सीवी में … की आवश्यकता नहीं होती"); none in any of the 7 notebooks or drafts. |

**Release gate on these 7:** no case added an unsupported fact (all rounds) · 7 of 7 pass · officer review pending.

## What the first round found, and the fixes

| Found | Cause | Fix |
|---|---|---|
| Kannada name, languages, job rejected; Hindi "yes" and "no" not recognised | The text normaliser stripped Indic vowel signs: "हाँ" became "ह", "ಕನ್ನಡ" became "ಕನ ನಡ" | Keep combining marks |
| Kannada quote rejected | The model copied a Kannada word with a look-alike Telugu letter, or dropped a word | Map Telugu letters to Kannada; a quote matches if all its words are in one answer |
| Language saved with English evidence for a Kannada answer | Model translated the quote | For Kannada/Hindi answers, fall back to the student's latest answer (numbers still checked) |
| "ಎರಡು ವರ್ಷ" (two years) rejected | Only digits and English number words understood | Kannada and Hindi number words |
| "ಮಾಡಿಲ್ಲ" (haven't done) not a "no" | "no" fused onto the verb | Recognise the suffix; "fresher" in Hindi/Kannada script |
| Saved "Tiwari", "Simariya" though the student spelled otherwise | Model's spelling kept | The student's spelled letters win and count as confirmation |
| Role "Computer Operator" rejected | Role had to match one quote | Role may match anything the student said |
| "```json {}```" and "比如" in the agent's speech | Model leakage | Stripped before display |
| Voice session closed while the draft was being written | 60 s silence timer | Paused while drafting |
| Draft failed: "429 RESOURCE_EXHAUSTED" | Free-trial per-minute quota with several students drafting | Retry after 4 s and 10 s |
| Draft blocked after a Kannada "anything else?" | Unrecognised wording | Broader Kannada/Hindi detection |
| Design request postponed | The voice agent can't see taps; thought the CV wasn't ready | Taps (Looks good, screen changes) are relayed to the agent |

Every fix has a test built from the evaluation's own sentences, and each was broken on purpose to confirm
the test fails (139 tests in total).

## Next

- Run the remaining 8 of the spec's 15 cases, and the 7 above again with real voice.
- Placement officer reviews the 7 final CVs.
- Watch the agent's first reply language for Hindi speakers (English for the first few turns in one case).
