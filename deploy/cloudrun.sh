#!/usr/bin/env bash
# Deploy Rockstar Radar (DEMO/beta) to Google Cloud Run — free tier, HTTPS, scales to zero.
# Usage:  bash deploy/cloudrun.sh [PROJECT_ID]
# Prereq: run `gcloud auth login` once first (interactive).
set -euo pipefail

PROJECT="${1:-rockstar-radar-beta}"
REGION="${REGION:-asia-south1}"          # Mumbai — closest for India beta users
SERVICE="${SERVICE:-rockstar-radar}"

echo "▶ Project: $PROJECT | Region: $REGION | Service: $SERVICE"

# 1. Create the project if it doesn't exist (isolated from your other work).
if ! gcloud projects describe "$PROJECT" >/dev/null 2>&1; then
  echo "▶ Creating project $PROJECT …"
  gcloud projects create "$PROJECT" --name="Rockstar Radar"
fi

# 2. Link a billing account (free-tier usage bills ₹0; account just required on file).
if ! gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  BA="$(gcloud billing accounts list --filter=open=true --format='value(name)' | head -1)"
  if [ -z "$BA" ]; then
    echo "✗ No open billing account found. Create/attach one in the Cloud Console, then re-run." >&2
    exit 1
  fi
  echo "▶ Linking billing account $BA …"
  gcloud billing projects link "$PROJECT" --billing-account="$BA"
fi

gcloud config set project "$PROJECT" >/dev/null

# 3. Enable the APIs Cloud Run + source deploy need.
echo "▶ Enabling APIs (run, cloudbuild, artifactregistry) …"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# 4. Build from source (Cloud Build uses our Dockerfile) and deploy, publicly, in DEMO mode.
echo "▶ Deploying (Cloud Build + Cloud Run) …"
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi --cpu 1 \
  --min-instances 0 --max-instances 2 \
  --set-env-vars RADAR_DEMO=1,RADAR_AUTOSTART=1

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo ""
echo "✅ Live beta URL:  $URL"
echo "   (DEMO mode — simulated data, no credentials, no real money.)"
