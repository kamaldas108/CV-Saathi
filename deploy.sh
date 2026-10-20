#!/usr/bin/env bash
# Deploy CV-Saathi to Google Cloud Run. Run from the repo root after `gcloud auth login`.
# See docs/deploy.md for what each step does and why.
set -euo pipefail

PROJECT="${PROJECT:-cv-saathi}"
REGION="${REGION:-asia-south1}"          # where the web server runs (Mumbai)
SERVICE="${SERVICE:-cv-saathi}"
SA_NAME="cv-saathi-run"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT"

# APIs Cloud Run needs to build and run the container, plus Vertex AI.
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com

# A service account that may only call Vertex AI models: no key file, nothing else.
if ! gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name "CV-Saathi Cloud Run"
fi
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:${SA}" \
  --role roles/aiplatform.user --condition=None >/dev/null

# --max-instances 1: sessions live in server memory, so every student must reach the same instance.
# --timeout 3600: a voice interview holds a WebSocket open for up to 10 minutes.
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account "$SA" \
  --allow-unauthenticated \
  --max-instances 1 \
  --concurrency 80 \
  --timeout 3600 \
  --memory 1Gi \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=us-central1,CVS_LIVE_MODEL=gemini-3.8-live,CVS_DRAFT_MODEL=gemini-3.8-flash,CVS_DRAFT_LOCATION=global,CVS_MAX_LIVE=5" \
  --quiet

gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)'
