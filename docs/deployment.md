# Deployment

Deploy the API as a Docker service on either Render or Google Cloud Run, and deploy `frontend/` as a separate Vercel project. Use a managed PostgreSQL database reachable from the API. Do not use SQLite.

The frontend already rewrites `/api/*` to `BACKEND_URL` in `frontend/next.config.ts`. This keeps browser requests and the session cookie on the Vercel origin.

## Backend environment

Set these values in the backend host:

| Variable               | Value                                                                             |
| ---------------------- | --------------------------------------------------------------------------------- |
| `ENV`                  | `production`                                                                      |
| `DATABASE_URL`         | PostgreSQL URL for normal API traffic; use the provider's pooled URL if available |
| `DATABASE_DIRECT_URL`  | Direct PostgreSQL URL for Alembic migrations                                      |
| `SESSION_SECRET`       | Random secret of at least 32 characters                                           |
| `WEB_ORIGIN`           | Stable Vercel production origin, such as `https://your-project.vercel.app`        |
| `GOOGLE_CLIENT_ID`     | Optional; needed with the next two values to enable Google sign-in                |
| `GOOGLE_CLIENT_SECRET` | Optional secret for Google sign-in                                                |
| `GOOGLE_REDIRECT_URI`  | `https://<backend-host>/api/v1/auth/google/callback`                              |
| `TRUSTED_PROXY_COUNT`  | Leave at `0` until the forwarded-header chain is confirmed for the selected hosts |

Keep secrets in the hosting provider's secret store. Set `MAX_UPLOAD_MB` and `MAX_IMPORT_ROWS` only if you intend to change the existing defaults (10 MB and 50,000 rows).

## Render

1. Create a Render Blueprint from this repository and select `render.yaml`.
2. Provide `DATABASE_URL`, `DATABASE_DIRECT_URL`, and `WEB_ORIGIN` when prompted. Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` in the Render dashboard only if Google sign-in will be enabled.
3. Render builds the Dockerfile from `backend/`, checks `/health`, and runs `python -m alembic upgrade head` before each deploy.
4. Set Vercel's `BACKEND_URL` to the Render service URL, then finish the Vercel steps below.

The Blueprint selects Render's `starter` web plan because Render requires a paid service plan for `preDeployCommand`.

## Google Cloud Run

Enable the Cloud Run, Cloud Build, Artifact Registry, and Secret Manager APIs. Create an Artifact Registry Docker repository named `reconcile`, and store these secrets in Secret Manager:

- `DATABASE_URL` — pooled URL for the API service.
- `DATABASE_DIRECT_URL` — direct URL used by the migration job.
- `SESSION_SECRET` — random value with at least 32 characters.
- `GOOGLE_CLIENT_SECRET` — only if enabling Google sign-in.

Create a `GOOGLE_CLIENT_ID` secret too if you prefer to keep all OAuth settings in Secret Manager; otherwise pass it as a normal environment variable. Grant the Cloud Run service identity access to the secrets it uses.

Run the following in PowerShell from the repository root. Replace the project and region values. The current commit short hash is used as the immutable image tag.

```powershell
$PROJECT_ID = "your-gcp-project"
$REGION = "us-central1"
$TAG = (git rev-parse --short HEAD).Trim()
$IMAGE = "$REGION-docker.pkg.dev/$PROJECT_ID/reconcile/backend:$TAG"

gcloud builds submit .\backend --project $PROJECT_ID --tag $IMAGE

gcloud run jobs deploy reconcile-migrate `
  --project $PROJECT_ID --region $REGION --image $IMAGE `
  --command python --args=-m,alembic,upgrade,head `
  --set-env-vars ENV=production `
  --set-secrets DATABASE_URL=DATABASE_DIRECT_URL:latest,SESSION_SECRET=SESSION_SECRET:latest `
  --execute-now --wait

gcloud run deploy reconcile-api `
  --project $PROJECT_ID --region $REGION --image $IMAGE `
  --port 8000 --allow-unauthenticated `
  --set-env-vars ENV=production,WEB_ORIGIN=https://your-project.vercel.app `
  --set-secrets DATABASE_URL=DATABASE_URL:latest,SESSION_SECRET=SESSION_SECRET:latest
```

If enabling Google sign-in, add `GOOGLE_CLIENT_ID` to `--set-env-vars` and `GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest` to `--set-secrets`. After the first service deployment, get its URL and configure the callback:

```powershell
$API_URL = (gcloud run services describe reconcile-api --project $PROJECT_ID --region $REGION --format='value(status.url)').Trim()
$GOOGLE_REDIRECT_URI = "$API_URL/api/v1/auth/google/callback"
gcloud run services update reconcile-api `
  --project $PROJECT_ID --region $REGION `
  --update-env-vars "GOOGLE_REDIRECT_URI=$GOOGLE_REDIRECT_URI"
```

Set the same callback URL in Google Cloud OAuth settings.

Run the migration job successfully before the first service deployment and after backend changes that add migrations. The Docker image listens on `0.0.0.0:$PORT`, as required by Cloud Run.

## Vercel

Create a Vercel project connected to this repository and set its **Root Directory** to `frontend`. Keep the detected Next.js framework, install command, and build command. Set `BACKEND_URL` in the Production environment to the public Render or Cloud Run service URL, without a trailing slash. Add it to Preview only if previews should call the same backend.

Use the stable production Vercel origin for the backend's `WEB_ORIGIN`. Register this exact OAuth callback with Google:

```text
https://<backend-host>/api/v1/auth/google/callback
```

Preview deployment URLs vary, so Google sign-in should be tested on the stable production URL unless separate OAuth credentials and callback configuration are created for previews.

## First-deploy checks

- Confirm `GET https://<backend-host>/health` returns `{"status":"ok","database":"ok"}`.
- Confirm a migration completed before the API accepted traffic.
- Sign in and verify the session cookie is `Secure`, `HttpOnly`, `SameSite=Lax`, and has no `Domain` attribute.
- Verify an upload through the Vercel URL at the configured maximum size. Vercel documents a 120-second maximum for proxied requests; larger request-body limits for external rewrites should be confirmed with a real upload before relying on the 10 MB application limit.
- `TRUSTED_PROXY_COUNT` controls how many rightmost `X-Forwarded-For` entries the backend trusts for IP-based rate limiting. Keep it at `0` until the complete Vercel-to-backend proxy chain is known; set it to the verified hop count to avoid treating all proxied users as one IP.

## Provider references

- [Render Blueprint YAML reference](https://render.com/docs/blueprint-spec)
- [Cloud Run container runtime contract](https://cloud.google.com/run/docs/container-contract)
- [Cloud Run jobs](https://cloud.google.com/run/docs/create-jobs)
- [Vercel external rewrites](https://vercel.com/docs/rewrites)
- [Vercel project root directory](https://vercel.com/docs/builds/configure-a-build#root-directory)
- [Vercel request and proxy limits](https://vercel.com/docs/limits)
