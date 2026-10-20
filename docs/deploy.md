# Deploying CV-Saathi to Google Cloud Run

**Why Cloud Run (not Vercel):** the voice interview holds a WebSocket open for up to 10 minutes and
sessions live in server memory. Vercel's serverless Python functions support neither. Cloud Run runs
the same server, bills to the project's credit, scales to zero when idle, and calls Vertex AI as a
service account with no key file.

## One-time sign-in

The gcloud CLI needs its own login (separate from the application-default login used locally):

```bash
gcloud auth login
```

## Deploy

```bash
bash deploy.sh
```

It enables the needed APIs, creates a service account `cv-saathi-run` that may only call Vertex AI
(`roles/aiplatform.user`), builds the container from `Dockerfile`, and deploys service `cv-saathi`
in **asia-south1** (Mumbai). It prints the public URL at the end. Redeploy the same way after changes.

## Settings and why

| Setting | Value | Why |
|---|---|---|
| Region | asia-south1 | Web server in India. The voice model still runs in us-central1 and drafting in `global` (see consent text). |
| `--allow-unauthenticated` | on | Product owner chose an open link (no access code) for the pilot. |
| `CVS_MAX_LIVE` | 5 | At most 5 voice interviews at once, so an open link can't drain the credit quickly. |
| `--max-instances` | 1 | Sessions are in memory; all students must reach the same instance. |
| `--timeout` | 3600 s | WebSocket for a 10-minute interview. |
| `CVS_LOG_TOOLS` | not set | Tool logging prints CV data; keep it off in the cloud. Usage (token counts only) is logged. |

## Known limits (pilot)

- Sessions and share links are in memory: a redeploy, or the instance scaling to zero after a quiet
  period, ends unfinished sessions and expires share links. Persistent drafts (F11) are the fix.
- `.env`, `data/`, `.venv/` and tests are excluded from the upload (`.gcloudignore`).
- Set billing budget alerts ($50 / $150 / $250) before sharing the link widely.
