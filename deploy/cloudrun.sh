#!/usr/bin/env sh
# Build backend/ with its Dockerfile and deploy it to Cloud Run.
# Secrets and DATABASE_URL stay in Cloud Run (console or Secret Manager), not here.
set -eu

SERVICE="${SERVICE:-reconcile-api}"
REGION="${REGION:-us-central1}"

gcloud run deploy "$SERVICE" \
  --source backend \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars ENV=production,TRUSTED_PROXY_COUNT=0
