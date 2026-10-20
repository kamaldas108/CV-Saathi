# Switching on the voice interview: Google Cloud and Vertex AI setup

Without these steps, CV-Saathi runs in **sample mode**: a scripted text helper, not the AI. Everything
else (notebook, rules, templates, review, PDF, share) works the same. These steps switch on the real
Gemini Live voice interview, paid for by your $300 Google Cloud free-trial credit.

> Why Vertex AI and not an AI Studio API key: the $300 credit does not pay for Gemini calls made with
> an AI Studio key. Calls through Vertex AI on your Cloud project do draw on it.

## 1. Start the free trial and create a project

1. Go to <https://console.cloud.google.com/> and sign in with the Google account that has the credit.
2. If asked, activate the free trial ($300, valid 90 days). A card is needed for identity; the trial
   does not charge it unless you upgrade.
3. Create a project (top bar → project picker → **New project**). Name it e.g. `cv-saathi`.
   Note the **Project ID** (it may differ from the name, e.g. `cv-saathi-461203`).

## 2. Set budget alerts first

**Billing → Budgets & alerts → Create budget** for this project, amount $300, with alert thresholds at
**$50, $150 and $250** (the spec's numbers). Alerts email you; they do not stop spending.

## 3. Enable the Vertex AI API

Vertex AI has been renamed **Gemini Enterprise Agent Platform** in the console, so searching for
"Vertex AI API" may find nothing. Open the API page directly (its ID is still `aiplatform.googleapis.com`)
and click **Enable**:

<https://console.cloud.google.com/apis/library/aiplatform.googleapis.com>

Or search the API Library for **Agent Platform**, or run
`gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID`.
Menu names later in this guide ("Vertex AI → Model Garden") may also appear under the new name.

## 4. Check where the Live model is available

The spec prefers an India region (`asia-south1`, Mumbai). Gemini Live models are not offered in every
region, and preview models often start in `us-central1` only.

- In the console, open **Vertex AI → Model Garden**, find the Live model
  (Gemini 3.1 Flash Live Preview, or Gemini 3.8 Live), and note its exact **model ID** and the
  **regions** listed.
- If `asia-south1` is not listed, use a listed region and **say so in the consent text**
  (spec: Data, privacy and safety → Region). `web/index.html` holds the consent text.

## 5. Let your computer call Vertex AI

The simplest option for running on your own computer: sign in once with the gcloud CLI.

1. Install the Google Cloud CLI: <https://cloud.google.com/sdk/docs/install>
2. In a terminal:

   ```bash
   gcloud auth application-default login
   ```

   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

The Python SDK picks up these credentials automatically. No key file is needed.

*Alternative (service account key):* **IAM & Admin → Service accounts → Create**, give it the
**Vertex AI User** role, create a JSON key, save it **outside the repo**, and set
`GOOGLE_APPLICATION_CREDENTIALS` to its path in `.env`. Keys are long-lived secrets; prefer the gcloud
login for local work. When the app is deployed to Cloud Run, attach the service account to the service
instead of using a key.

## 6. Fill in `.env`

Copy `.env.example` to `.env` (it is gitignored) and set:

```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1        # checked: gemini-3.8-live works here, not in asia-south1
CVS_LIVE_MODEL=gemini-3.8-live
```

## 7. Run and try it

```bash
.venv/Scripts/python -m uvicorn cvsaathi.server:app --port 8000
```

Open <http://localhost:8000>. The badge at the top should say **Voice**. Tap the microphone and talk.

- Browsers only allow the microphone on `localhost` or HTTPS. To test on a phone, the app has to be
  served over HTTPS (for example deployed to Cloud Run). That deployment is not part of this first pass.
- If the voice connection fails, the server terminal shows the error. Common causes: wrong model ID,
  model not available in the region, Vertex AI API not enabled, or not signed in (step 5).

## 8. Measure the cost

Each voice session appends a line to `data/usage.jsonl` with its length and the token counts the Live
API reported, by modality (audio in/out, text). The spec's per-CV estimate ranges from about $0.15 to
$3.20; the first pilot sessions decide which end is real. Compare with **Billing → Reports** after a day,
because the reported token counts have not yet been checked against the bill.
