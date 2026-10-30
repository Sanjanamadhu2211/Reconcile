# Reconcile

Reconciliation app with a FastAPI backend, PostgreSQL database, and Next.js frontend.

## Local development

- Backend setup and environment: see [`backend/.env.example`](backend/.env.example) and [`backend/pyproject.toml`](backend/pyproject.toml).
- Frontend: `cd frontend`, `bun install`, then `bun dev`.
- The frontend proxies `/api/*` to `BACKEND_URL`; locally this defaults to `http://localhost:8000`.

## Deployment

See [`docs/deployment.md`](docs/deployment.md) for Render, Google Cloud Run, Vercel, database, secrets, and Google OAuth setup.

The backend Docker image is in `backend/`. Render can use the root [`render.yaml`](render.yaml). Vercel's project root should be `frontend`.
