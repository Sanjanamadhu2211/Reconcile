# Reconcile — Implementation Plan

## 1. Product Overview

**Reconcile** is a full-stack transaction reconciliation platform for businesses that need to compare records from orders, payment providers, refunds, and settlement reports.

The product imports data from multiple sources, matches related records using configurable rules, surfaces discrepancies, and provides an auditable workflow for investigating and resolving them.

### Product goals

- Make reconciliation repeatable instead of spreadsheet-driven.
- Detect missing, duplicated, delayed, and mismatched transactions.
- Preserve an audit trail for imports, matches, decisions, and corrections.
- Demonstrate production-quality engineering: correctness, testing, CI/CD, deployment, and observability.

### Non-goals for the MVP

- Moving money or initiating real payments.
- Replacing a full accounting system.
- Supporting every payment provider.
- Using an LLM to decide financial matches.
- Building microservices before there is a demonstrated need.

## 2. Primary Users and Workflows

### Users

- **Analyst:** imports data, reviews discrepancies, and proposes resolutions.
- **Reviewer:** can do everything an analyst can, plus approve or reject proposals, reopen resolved exceptions, and manage members. The organization creator is a reviewer.

### Main workflow

1. Create an organization and reconciliation workspace.
2. Upload order, payment, refund, or settlement CSV files.
3. Map incoming columns to a canonical schema.
4. Validate the file and preview errors before processing.
5. Upload a CSV file in one synchronous HTTP request per file (max 10 MB and 50,000 rows; larger files are rejected with a clear error). For larger files, use `python -m app.cli import <file>`, which reuses the same import code with no row cap.
6. Match records and classify unmatched or ambiguous records.
7. Review discrepancies and record resolution decisions.
8. Export reconciliation results and inspect the audit history.

## 3. MVP Scope

### Core features

- Authentication and organization-level data isolation.
- Role-based access control (exactly two roles per organization: `analyst` and `reviewer`).
- Reconciliation workspaces and import batches.
- CSV upload, column mapping, validation, and error reporting.
- Request-driven import processing with status reporting.
- Deterministic matching rules (MVP scope):
  - Exact external transaction ID.
  - Amount plus currency equality within a configurable timestamp tolerance.
- Match classifications: matched, unmatched, ambiguous, and exception.
- Discrepancy queue with filters and search.
- Resolution workflow with notes and reviewer decisions: propose, approve, reject, reopen.
- Immutable audit events for imports and exception decisions.
- CSV export of matches, exceptions, and import errors via streaming GET endpoints.
- Dashboard showing import health, match rate, outstanding exceptions, and batch history.

### Explicitly deferred

- Direct bank/provider API integrations.
- Automated payouts or financial actions.
- Multi-currency foreign-exchange conversion.
- Machine-learning matching.
- Complex accounting rules and double-entry ledger functionality.
- Enterprise SSO and advanced policy configuration.
- Optional reference and merchant/order ID matching (stretch goal).

## 4. Technology Stack

Keep the system simple and deployable without a large infrastructure footprint.

- **Frontend:** Next.js + TypeScript, with Bun as package manager, script runner, and unit test runner (`bun.lock`, `bun test`)
- **Backend API:** Python + FastAPI
- **ORM and migrations:** SQLAlchemy + Alembic
- **Database:** PostgreSQL
- **Validation:** FastAPI's built-in request validation and Pydantic models.
- **Unit/integration tests:** Pytest for `backend/`, `bun test` for `frontend/`; two independent suites
- **Browser tests:** Playwright (run through `bunx`)
- **Local infrastructure:** none beyond a locally installed PostgreSQL; Docker is never run on the dev machine. CI uses a Postgres service container, and the backend image is only built in CI and by the host.
- **CI/CD:** GitHub Actions
- **Deployment:** Docker-compatible app hosting plus managed PostgreSQL
- **Observability:** structured JSON logs with request IDs and a health endpoint. Errors are read from the Render and Vercel log viewers; there is no Sentry.

Use a modular monolith: API and web are separate processes from the same codebase (no worker process). Do not introduce microservices for the MVP.

## 5. Key Design Decisions

- Synchronous bounded imports: one HTTP request per CSV file (max 10 MB, 50,000 rows), rows committed in chunks of 1,000 with each chunk in its own transaction, status kept in `import_batches`; a CLI path (`python -m app.cli import <file>`) reuses the same code with no row cap for larger files.
- NUMERIC money: amounts stored as PostgreSQL `NUMERIC(19,4)` with a 3-letter ISO 4217 currency code; Python `Decimal` throughout; decimal strings sent and received over the API.
- Idempotency by checksum: unique (`workspace_id`, `file_checksum`) on `import_batches`; completed batches are returned as-is, failed or stuck batches resume from `rows_processed` skipping committed row numbers; an `Idempotency-Key` header on `POST /imports` maps to the same batch.
- Tenant isolation by `organization_id`: every tenant table carries a non-null, indexed `organization_id` foreign key, and every API access is authorized.
- DB-enforced append-only audit: the application DB role has only INSERT and SELECT on `audit_events`, plus a trigger that raises on UPDATE or DELETE.
- Session cookie auth with CSRF: email/password OR Google sign-in, server-side PostgreSQL `sessions` table, HttpOnly Secure SameSite=Lax cookie, double-submit `X-CSRF-Token`.
- Two-step resolution: exception state machine open → proposed → resolved/open, with an optimistic version column (stale updates return 409).
- Same-origin deployment through a Vercel rewrite: no custom domain. The frontend is served from its automatic `<project>.vercel.app` address and a rewrite forwards `/api/*` to the backend on Render, so the browser only talks to one origin. The session cookie is host-only (no `Domain` attribute) and no CORS is needed; uploads go through the same rewrite.

ADRs to create under `docs/adr/` (one per bullet above):

- `0001-synchronous-bounded-imports.md`
- `0002-numeric-money.md`
- `0003-idempotency-by-checksum.md`
- `0004-tenant-isolation-by-organization-id.md`
- `0005-append-only-audit.md`
- `0006-session-cookie-auth-with-csrf.md`
- `0007-two-step-resolution.md`
- `0008-same-origin-deployment-via-rewrite.md`
- `0009-google-sign-in-plus-password-login.md`

## 6. Proposed Repository Structure

```text
reconcile/
├── frontend/                 # Next.js + TypeScript dashboard
│   ├── src/lib/api/          # Typed client (openapi-typescript + openapi-fetch) generated via `bun run gen:api` from the committed `backend/openapi.json`
│   ├── .env.example
│   └── e2e/                  # Playwright E2E tests (exactly 3 flows)
├── backend/                  # Python + FastAPI REST API
│   ├── app/
│   │   ├── routers/          # HTTP endpoints
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── auth/             # Authentication, sessions, CSRF, authorization helpers
│   │   ├── reconciliation/   # Matching engine and domain rules
│   │   └── imports/          # CSV parsing, mapping, validation
│   ├── alembic.ini
│   ├── alembic/              # Migrations
│   ├── Dockerfile
│   ├── .env.example
│   ├── scripts/              # seed_demo.py, benchmark.py
│   ├── tests/                # Pytest suites and fixtures
│   └── pyproject.toml
├── docs/
│   ├── architecture.md       # incl. Mermaid architecture diagram
│   ├── data-model.md
│   ├── security.md
│   └── adr/                  # one ADR per Key Design Decisions bullet
├── .github/workflows/
└── README.md                 # incl. setup, architecture, demo instructions, free-tier cold-start note
```

Keep module boundaries purposeful. Avoid creating a module for every small helper.

## 7. Domain Model

Use UUIDs for internal identifiers. Store money as PostgreSQL `NUMERIC(19,4)` with a 3-letter ISO 4217 currency code; use Python `Decimal` internally and send/receive amounts as decimal strings in the API and frontend. Never use floating-point numbers for financial arithmetic.

### Main tables

- **users:** identity and authentication fields (email, optional argon2-cffi password hash, optional unique `google_sub`); a user must have at least one of password hash or google_sub.
- **organizations:** tenant/business account.
- **organization_memberships:** user, organization, role (`analyst` or `reviewer`); exactly two roles per organization; the organization creator is a reviewer.
- **workspaces:** reconciliation configuration and ownership; non-null indexed `organization_id` foreign key.
- **import_batches:** workspace, `source_name` text, file metadata (no raw CSV stored), status (pending, processing, completed, failed), rows_total, rows_processed, rows_failed, error_summary, started_at, updated_at, file_checksum; unique (`workspace_id`, `file_checksum`).
- **import_rows:** batch, row number, normalized payload, validation status, error details; non-null indexed `organization_id`.
- **transactions:** canonical normalized financial records, `source_name` text, external ID, amount `NUMERIC(19,4)`, currency code, transaction type, reference, occurrence time; unique (`workspace_id`, `source_name`, `external_id`); non-null indexed `organization_id`.
- **reconciliation_runs:** batch/workspace scope, rule version, status, counters, timestamps; non-null indexed `organization_id`.
- **matches:** reconciliation run, matched transaction IDs, `rule` (the deterministic rule that produced the match), status; a unique (`reconciliation_run_id`, `transaction_id`) constraint on each matched transaction column makes double matching impossible; non-null indexed `organization_id`.
- **exceptions:** unmatched/ambiguous records, category, status (open, proposed, resolved), assigned reviewer, version; non-null indexed `organization_id`.
- **resolutions:** exception, actor, decision, note, timestamp, version; non-null indexed `organization_id`.
- **audit_events:** organization, actor, action, target, metadata, timestamp — import events and exception propose/approve/reject/reopen only.

### Important constraints

- Scope tenant-owned data by `organization_id` and authorize every access; every tenant table (workspaces, import_batches, transactions, import_rows, reconciliation_runs, matches, exceptions, resolutions, audit_events) has a non-null, indexed `organization_id` foreign key.
- Rows are processed and committed in chunks of 1,000, each chunk in its own transaction.
- Use database transactions for match creation and resolution updates.
- Preserve original input and normalized values so decisions can be explained.
- Version matching rules used by each reconciliation run.
- Enforce append-only `audit_events` in the database: the application DB role gets only INSERT and SELECT on `audit_events`, plus a trigger that raises on UPDATE or DELETE.
- Use an idempotency key or deterministic import identity to prevent duplicate imports: unique (`workspace_id`, `file_checksum`) on `import_batches`, plus an `Idempotency-Key` header on `POST /imports`.

### Roles (exactly two per organization)

| Role | Can do |
|------|--------|
| Analyst | Upload imports, run matching, view everything, propose exception resolutions |
| Reviewer | Everything an analyst can, plus approve or reject proposals, reopen resolved exceptions, manage members |

Rules: the organization creator is a reviewer; a reviewer cannot approve their own proposal.

### Exception state machine

- `open` → `proposed`: an analyst proposes a resolution with a note.
- `proposed` → `resolved`: a reviewer approves; or → `open`: a reviewer rejects (note required).
- `resolved` → `open`: a reviewer reopens (note required).

API: `POST /exceptions/{id}/propose`, `/approve`, `/reject`, `/reopen`. Resolution updates use an optimistic version column; a stale update returns 409.

## 8. API Design

Use versioned REST endpoints, consistent error envelopes, pagination, and request validation.

### Example endpoints

```text
POST   /api/v1/organizations
GET    /api/v1/workspaces
POST   /api/v1/workspaces
GET    /api/v1/workspaces/:workspaceId

POST   /api/v1/workspaces/:workspaceId/imports
GET    /api/v1/imports/:importId
GET    /api/v1/imports/:importId/errors

POST   /api/v1/workspaces/:workspaceId/reconciliation-runs
GET    /api/v1/reconciliation-runs/:runId
GET    /api/v1/reconciliation-runs/:runId/matches
GET    /api/v1/reconciliation-runs/:runId/exceptions

POST   /api/v1/exceptions/:exceptionId/propose
POST   /api/v1/exceptions/:exceptionId/approve
POST   /api/v1/exceptions/:exceptionId/reject
POST   /api/v1/exceptions/:exceptionId/reopen
GET    /api/v1/audit-events

GET    /api/v1/workspaces/:workspaceId/exports/matches.csv
GET    /api/v1/workspaces/:workspaceId/exports/exceptions.csv
GET    /api/v1/workspaces/:workspaceId/exports/import-errors.csv

# Authentication
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
GET    /api/v1/auth/google/login
GET    /api/v1/auth/google/callback
```

Upload endpoints create a batch and process the CSV in one synchronous HTTP request per file (max 10 MB and 50,000 rows; larger files are rejected with a clear error). Rows are committed in chunks of 1,000, each chunk in its own transaction. Progress and status live in the database on `import_batches` (status: pending, processing, completed, failed; rows_total, rows_processed, rows_failed, error_summary, started_at, updated_at). The browser polls `GET /imports/{id}` from a second request while the upload runs. Raw CSV files are not stored (PII); only normalized rows are kept. Larger files use the CLI command `python -m app.cli import <file>`, which reuses the same import code with no row cap. Uploading the same file again returns the existing batch if completed, or resumes from `rows_processed` (skipping committed row numbers) if failed or stuck in processing with `updated_at` older than 5 minutes; an `Idempotency-Key` header on `POST /imports` maps to the same batch. Use cursor or bounded pagination for potentially large result sets.

## 9. Matching Engine Design

Start with deterministic, explainable rules. Every match carries the `rule` that produced it; matching is deterministic, not probabilistic, so there is no confidence score.

### Matching stages (MVP scope)

1. Normalize identifiers, timestamps, currencies, and transaction types.
2. Reject invalid rows into a visible error collection.
3. Match exact external transaction IDs.
4. Match remaining records on amount plus currency equality within the configured timestamp tolerance.
5. Mark candidate sets with more than one match as ambiguous; everything else stays unmatched.
6. Persist the outcome with rule version and the `rule` that produced the match.

### Correctness rules

- Never silently discard a row.
- Never force a match when more than one candidate satisfies the rule.
- Make rerunning a reconciliation run safe and reproducible.
- Avoid mutating source transaction records when changing a match decision.
- Document tie-breaking rules and test them explicitly.
- Ambiguous candidates stay a classification; they are never auto-resolved.

## 10. Security and Reliability

- Hash passwords with argon2-cffi; login is email/password OR Google sign-in through OpenID Connect.
- Enforce tenant boundaries in the API and test cross-tenant access denial.
- Validate uploads by size (max 10 MB), file type, encoding, and row count (max 50,000 rows).
- Never trust a filename or MIME type as the only upload validation.
- Do not store raw CSV files (PII); only normalized rows are kept.
- Keep secrets in deployment secret stores, not committed environment files.
- Rate-limit authentication and expensive endpoints.
- Use parameterized queries and output escaping.
- Use least-privilege database and service credentials (app DB role: INSERT/SELECT only on `audit_events`, plus the append-only trigger).
- Session auth: email/password OR Google sign-in, server-side PostgreSQL `sessions` table, session in an HttpOnly, Secure, SameSite=Lax cookie.
- CSRF: double-submit token; state-changing requests must send an `X-CSRF-Token` header matching the csrf cookie.
- Redact credentials and sensitive data from logs.
- Make imports idempotent: unique (`workspace_id`, `file_checksum`), completed batches are returned as-is, failed or stuck batches resume from `rows_processed`, and import retries are safe.
- Handle import failures gracefully: chunks of 1,000 rows each committed in their own transaction, with resume from `rows_processed`.

### Google sign-in

- OpenID Connect authorization code flow with PKCE and a `state` parameter, implemented in FastAPI with Authlib. The backend handles the callback, creates the same server-side session as password login, then redirects the browser to the web app.
- Scopes: `openid email profile` only, which need no Google app verification.
- Verify the ID token (signature, issuer, audience, expiry) and require `email_verified` to be true.
- Account linking: look up the user by Google `sub` first; otherwise link to an existing user with the same verified email; otherwise create a new user. A new Google user has no organization until they create one or are invited. Never link by an unverified email.
- Register the redirect URI separately for local and the stable Vercel address (`https://<project>.vercel.app/api/v1/auth/google/callback`, proxied to the backend). Preview deployment URLs change on every deploy, so Google sign-in works only on the stable address; previews use the demo login. The OAuth consent screen uses the External user type.

### Environment variables

See `backend/.env.example` (the frontend folder has its own `frontend/.env.example` with the API base URL). Only `DATABASE_URL` and `SESSION_SECRET` are required; the rest are optional and off when empty: `DATABASE_URL`, `DATABASE_DIRECT_URL`, `SESSION_SECRET`, `WEB_ORIGIN`, `MAX_UPLOAD_MB`, `MAX_IMPORT_ROWS`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.

## 11. Testing Strategy

### Unit tests

- Money parsing and normalization (`Decimal`, `NUMERIC(19,4)`, decimal strings over the API).
- Timestamp normalization and tolerance boundaries.
- Matching rule precedence and ambiguous matches.
- Duplicate detection and checksum logic.
- Import row validation.
- Role/permission decisions (role matrix).

### Integration tests

- Migrations against a real PostgreSQL test database.
- Import creation and duplicate submission behavior (checksum idempotency, `Idempotency-Key` header).
- Synchronous import processing and idempotency/resume: resume from `rows_processed`, skipping committed row numbers; chunks of 1,000 each in its own transaction.
- Transaction rollback on partial failures.
- Tenant isolation: organization A can never read organization B data at the API level.
- Concurrent resolution attempts: 409 on stale version.
- Match creation constraints and rerun behavior.
- Golden-fixture tests: committed CSV fixtures with committed expected outputs.

### End-to-end tests (Playwright, exactly three flows)

1. Sign in, create a workspace, import a CSV, and watch batch status via polling.
2. Review discrepancies, propose and approve an exception.
3. Export matches, exceptions, and import errors as CSV.

Note: Playwright flows keep using the seeded email-and-password demo login; the Google sign-in flow is tested with Pytest using a mocked token exchange: valid login, unverified email rejected, wrong audience rejected, linking by `sub`, and linking by verified email.

### Quality gates

- Lint and formatting checks.
- Type checking.
- Unit and integration tests.
- Production build.
- Dependency and secret scanning.
- OpenAPI client drift check (CI fails if the generated client is out of date).
- Separate suites: `backend/tests` (Pytest, `unit/` and `integration/`) and `frontend/src/**/*.test.ts(x)` (`bun test`). Each runs in its own CI job, and only when its folder changes.
- E2E smoke suite against staging.
- Test the failure paths, not only the happy path.
- The performance suite is one benchmark script, `backend/scripts/benchmark.py`, which seeds 10k to 100k synthetic rows with a known match/exception ratio and records rows per second and match accuracy in the README.

## 12. CI/CD and Deployment

### CI workflow (push to `dev` and `main`)

Separate workflow files so the two sides run in parallel and only when their folder changes (`paths:` filters, each including its own workflow file):

- `backend.yml` (on `backend/**`): jobs `lint` (Ruff format and check), `test` (Pytest with coverage against a Postgres service container, migrations applied first), `audit` (pip-audit), `build` (Docker image). The jobs run in parallel.
- `frontend.yml` (on `frontend/**`): jobs `lint` (ESLint, Prettier check, `tsc`), `test` (`bun test`), `build` (`bun run build`). Dependencies come from `bun install --frozen-lockfile`. The jobs run in parallel.
- `contract.yml` (on `backend/**` and `frontend/**`): regenerates `backend/openapi.json` and the typed client and fails if either differs from what is committed.
- `security.yml` (every push): gitleaks.
- `e2e.yml` (on `backend/**` or `frontend/**`, added in Phase 7): Playwright against a local stack.

CI needs no real secrets or external services. It uses a Postgres service container and fixed dummy values for settings (see 13.1, external connections).

Dependabot is enabled.

### Staging workflow

1. Build versioned Docker images.
2. Push images to a container registry.
3. Deploy API and web app to staging (no worker component).
4. Apply backward-compatible database migrations (`alembic upgrade head` as a pre-deploy step, never at app startup).
5. Run health checks and Playwright smoke tests.
6. Publish deployment metadata and logs.

### Production workflow (optional, only if budget allows)

- Deploy the same tested image to production (Vercel manages its own deployments for the web app; there is no image to promote).
- Use protected production environments and approval if appropriate.
- Run backward-compatible migrations before application rollout (`alembic upgrade head` as a pre-deploy step on Render, or a one-off Cloud Run job, never at app startup).
- Verify readiness and critical workflows.
- Maintain a rollback procedure and migration recovery notes.
- Never assume rolling back application code automatically rolls back a database migration.

### Operational requirements

- Deployment: frontend on Vercel; API as one host-agnostic Docker image that deploys to either Render or GCP Cloud Run (both are supported and documented; the choice is made at the end, and the Vercel rewrite target is a single `BACKEND_URL` setting). Database on Neon free tier: pooled URL for the app, direct URL for Alembic.
- No custom domain. The web app is served from its automatic Vercel address (`<project>.vercel.app`) and a Vercel rewrite forwards `/api/*` to the Render API, so the browser sees one origin: the session cookie is host-only and no CORS is needed. The backend trusts forwarded headers from the proxy only.
- File uploads (max 10 MB) go through the same rewrite. Vercel limits Function request bodies to about 4.5 MB; whether that applies to rewrites to an external origin is unverified and must be tested in Phase 8. If it does apply, fall back to direct browser-to-API uploads with a `SameSite=None; Secure` cookie plus the CSRF token, or lower the web upload cap.
- Single `/health` endpoint that also checks the database (no separate `/ready`).
- Structured JSON logs with request IDs, read through the Render and Vercel log viewers. No Sentry or alerting service.
- Metrics for import duration, rows/second, match rate, exception rate.
- A documented manual `pg_dump` script plus Neon's built-in history (replaces scheduled backups); tested restore procedure.
- Separate staging and (optional) production secrets and data.
- DB pool: SQLAlchemy `pool_size=5`, `max_overflow=5`, `pool_pre_ping=True`; single uvicorn worker.
- Migrations: run the Alembic upgrade as a pre-deploy step on Render or as a Cloud Run job, never at app startup.
- README note: free tiers cold-start after idle.
- Note: free-tier limits (Vercel body size, Render request timeout of roughly 100 s) are stated from memory and must be re-checked against current docs before launch.

## 13. Phased Build Plan

Nine phases (0 to 8). Subagents do the work; the orchestrator plans, dispatches, checks, and reports.

### 13.1 Delivery rules

**Branches**
- All work lands on `dev`. `main` is never touched.
- Each subagent slice runs in its own worktree on a branch `dev-p<N>-<slice>` cut from `dev`, and is squash-merged back into `dev` once its gate is green.
- Nothing is pushed until the user says so. The expected push point is the end of a phase, on `dev` only.

**Checkpoint commits**
- A checkpoint is one commit on `dev` that leaves the whole tree green. Each phase has 2 to 4 of them, listed under the phase.
- One checkpoint per integrated slice or slice group. No commit per file, per subagent step, or for WIP. If a slice is small, fold it into the next checkpoint.
- A checkpoint is only made after its gate passes. A failing gate means fix first, then commit, never commit red.
- Messages follow the workspace rules: short, plain, human, no `feat:`/`fix:` prefix, no emoji, no attribution lines. Author is `Sanjanamadhu2211`.
- When a phase passes its exit criteria, tag the last checkpoint `phase-<N>-done` (local tag).

**Revert path**
- Every checkpoint and every `phase-<N>-done` tag is a known-good point.
- Before pushing: reset `dev` to the last good checkpoint (only after the user confirms).
- After pushing: `git revert <checkpoint>`; history is never rewritten on a pushed branch.
- A checkpoint that adds a migration holds exactly one Alembic revision with a working `downgrade()`. Reverting it means downgrading one revision, then the git revert. The gate runs upgrade, downgrade, upgrade once to prove it.

**Subagent dispatch**
- Orchestrator calls `orchestrator_capabilities` once, then hands out slices round robin: MiMo V2.6 Flash, Nemotron 3.5 Super VL, North Mini Code, repeat. A rate-limited model is skipped for that turn and swapped for a backup. Haiku only on escalation (retry once on the same model with the exact failure, then the next model, then Haiku), and the report says when it was used.
- Never run Docker locally: no `docker`, `docker compose`, or container builds in briefs or by agents. Servers run locally (`uvicorn`, `bun run dev`). Database-dependent tests skip when no database is reachable and run in CI.
- Max 5 subagents at once. Slices running in parallel own disjoint directories; shared files (`app/main.py` router registration, `pyproject.toml`, `package.json`) are touched by one named slice only, and the rest add their own files.
- Migrations are never written in parallel. Each phase has a schema step (x.0) done by one agent before the parallel slices start, so there is one Alembic head at all times.
- Each brief is self-contained: exact paths, goal, interfaces to honour, what must not change, stack, numbered steps, the gate commands, the git rules, and the fixed report format (files changed, commands run with pass/fail, commits, skipped or unsure).
- Security-sensitive slices (auth, Google OIDC, tenant isolation, audit trigger and grants, money parsing, matching rules) get a second-model review of the diff before their checkpoint.

**Orchestrator check after each slice** (no code re-reading): `git log --oneline`, `git diff --stat`, then the gate commands. Clean output means accept.

**Gates** (use whatever exists at that phase; CI runs the same commands)
- API: `cd backend && ruff check . && ruff format --check . && pytest -q`
- Web: `cd frontend && bun install --frozen-lockfile && bun run lint && bunx tsc --noEmit && bun test && bun run build`
- Client drift (from Phase 6): regenerate `backend/openapi.json` and run `cd frontend && bun run gen:api`, then `git diff --exit-code`.
- Migration round trip (any phase with a migration): upgrade to head, downgrade one revision, upgrade to head again.

**Tests.** Tests are written together with the code, in the same slice and the same checkpoint, never in a later pass. A slice brief lists the tests it must add, and a slice without them is not accepted. Tests are committed and pushed with the code (this overrides the workspace default for tests only). Docs, including ADRs and the README, stay local and unpushed until the user asks.

**CI first.** The CI workflows (section 12) are the very first checkpoint of the build (step 0.0), before any application code. From then on every push to `dev` or `main` runs them in the background, so each checkpoint is checked remotely as well as locally. Until `backend/` and `frontend/` exist, the workflows detect the missing folder and pass without doing anything.

**Separate deployables.** `backend/` and `frontend/` are fully independent: own dependency lockfile (`pyproject.toml` and `bun.lock`), own `.env.example`, own tests, no imports across the folders. The only link is the committed `backend/openapi.json`, from which `frontend` generates its client. The repo root holds only Compose, CI, and docs, so each folder can be deployed on its own (`backend/Dockerfile` for Render, `frontend/` for Vercel).

**External connections do not block the build.** Only `DATABASE_URL` and `SESSION_SECRET` are required, and both have local defaults (Compose Postgres, a dev secret). Google, Neon pooling, Render, and Vercel are all optional settings: empty means the feature is off (Google login hidden and its routes return 503). Tests mock Google and never need real credentials. CI uses dummy values. Real values are wired in during Phase 8, supplied by the user at the end.

**Tasks only the user can do, all at the end (Phase 8):** create the Google Cloud OAuth client, create the Neon and Vercel accounts, plus a Render or GCP account (whichever backend host is used), and projects, provide secrets, record the walkthrough video, and re-check the free-tier limits flagged in section 12.

### Phase 0 — Define the contract

Goal: requirements and fixtures make expected reconciliation results unambiguous.

Order: 0.0 first, then 0a, then 0b and 0c in parallel.
- **0.0 CI** (`.github/workflows/`): the five workflows from section 12 with `paths:` filters, triggered on push to `dev` and `main`, plus Dependabot for pip and bun. Guarded so they pass while `backend/` and `frontend/` are absent. Own checkpoint, first of all.
- **0a Canonical schema and CSV formats** (`docs/data-model.md`): canonical transaction fields, per-source CSV layouts, column mapping rules, key invariants.
- **0b Fixtures** (`backend/tests/fixtures/`): sample CSVs for orders, payments, refunds, settlements covering exact matches, missing records, duplicates, refunds, fees, malformed rows, ambiguous candidates; each with a committed expected-output file. Fixtures are tests and are committed.
- **0c Architecture and ADRs** (`docs/architecture.md` with the Mermaid diagram, `docs/security.md` skeleton, `docs/adr/0001` to `0009`).

Checkpoints: (1) CI workflows; (2) canonical schema and CSV formats; (3) fixtures and expected outputs; (4) architecture diagram and ADRs.

Gate: a small script confirms every input row appears in exactly one expected category (no row unaccounted for).

Exit: expected outcome for every fixture row is written down and unambiguous.

### Phase 1 — Repository and local environment

Goal: a fresh clone starts locally and passes CI.

Parallel slices (disjoint directories):
- **1a API skeleton** (`backend/`): `pyproject.toml`, app factory, validated settings, `/health` with DB check, JSON logs with request IDs, Dockerfile, Pytest (`tests/unit`, `tests/integration`) and Ruff setup, DB test fixture, one smoke test per suite.
- **1b Web skeleton** (`frontend/`): Next.js + TypeScript, Bun (`bun.lock`), ESLint, Prettier, `bun test` with one smoke test, placeholder page.
- **1c CI cleanup**: remove the empty-folder guards from `backend.yml` and `frontend.yml` now that both folders exist (`contract.yml` keeps its guard until Phase 6). Each folder carries its own `.env.example`.

Checkpoints: (1) API skeleton plus Compose; (2) web skeleton; (3) CI guards removed and green on both folders.

Gate: API gate and web gate from a clean checkout (DB-dependent tests skip locally when no database is reachable and run in CI), and the first CI run is green.

Exit: fresh clone runs locally, CI config in place.

### Phase 2 — Identity and tenancy

Goal: users can only reach their own organization's data.

- **2.0 Schema** (one agent): models and one Alembic revision for `users`, `organizations`, `organization_memberships`, `workspaces`, `sessions`; Alembic on `DATABASE_DIRECT_URL`; engine pool settings. Checkpoint (1).
- **2a Password auth** (`app/auth/`, `routers/auth.py`): argon2-cffi, PostgreSQL sessions, HttpOnly Secure SameSite=Lax cookie, double-submit CSRF, login rate limit. Checkpoint (2).
- Then in parallel:
  - **2b Google sign-in** (`app/auth/google.py`): Authlib OIDC, PKCE, `state`, ID token checks, verified-email linking, reuses 2a's session helper; Pytest with mocked token exchange (valid, unverified email, wrong audience, link by `sub`, link by verified email).
  - **2c Orgs, roles, workspaces** (`routers/organizations.py`, `routers/workspaces.py`, `app/auth/permissions.py`): create org (creator becomes reviewer), memberships, analyst/reviewer dependency, workspace CRUD scoped by `organization_id`. Checkpoint (3) once both merge.
- **2d Tenant isolation tests**: cross-tenant denial for every endpoint so far, role matrix; second-model review of the auth diff. Checkpoint (4).

Gate: API gate plus migration round trip.

Exit: cross-tenant access is denied and tested; both login paths create the same session.

### Phase 3 — Import pipeline

Goal: duplicate submission is safe, bad rows are visible, imports resume, the CLI handles big files.

- **3.0 Schema** (one agent): `import_batches` (unique `workspace_id`, `file_checksum`), `import_rows`, `transactions` (unique `workspace_id`, `source_name`, `external_id`), all with non-null indexed `organization_id`.
- **3a Parse, map, validate** (`app/imports/`): streaming CSV, encoding and size and row caps (10 MB, 50,000), column mapping, `Decimal` money, timestamp and currency normalization. Pure functions. Checkpoint (1) with 3.0.
- **3b Processor** (`app/imports/processor.py`): checksum, chunks of 1,000 each in its own transaction, `rows_processed` and status updates, resume skipping committed row numbers, stuck-after-5-minutes rule, never discards a row silently. Checkpoint (2).
- Then in parallel:
  - **3c Endpoints** (`routers/imports.py`): upload, preview, `GET /imports/{id}`, `/errors`, `Idempotency-Key`.
  - **3d CLI** (`app/cli.py`): `python -m app.cli import <file>`, same code path, no row cap. Checkpoint (3).

Gate: API gate plus migration round trip. Required tests: crash mid-file then resume, double upload, size and row-cap rejection, golden fixtures for import errors.

Exit: duplicate submission is safe, invalid rows are visible, imports resume from `rows_processed`, and the CLI path handles larger files with no row cap.

### Phase 4 — Matching engine

Goal: fixtures produce deterministic results; reruns never duplicate outcomes.

- **4.0 Schema** (one agent): `reconciliation_runs`, `matches` (unique `reconciliation_run_id`, `transaction_id` per matched column), `exceptions`.
- **4a Engine** (`app/reconciliation/`): normalization, exact-ID rule, amount plus currency within tolerance, ambiguous classification, documented tie-breaks. Pure and unit-tested. Checkpoint (1) with 4.0.
- **4b Persistence** (`app/reconciliation/runner.py`): run in one DB transaction, rule version and `rule` stored, rerun replaces its own outputs safely, source transactions never mutated. Checkpoint (2).
- **4c Endpoints** (`routers/reconciliation.py`): create run, get run, list matches and exceptions with filters, search, and bounded pagination. Checkpoint (3).

Gate: API gate plus migration round trip. Required tests: golden fixtures from Phase 0, rerun idempotency, two concurrent runs, ambiguous never auto-resolved.

Exit: results match the committed expected outputs exactly.

### Phase 5 — Review and audit

Goal: every resolution is attributable and explainable.

- **5.0 Schema** (one agent): `resolutions`, `audit_events`, the UPDATE/DELETE-raising trigger, and the least-privilege app DB role (INSERT and SELECT only on `audit_events`).
- **5a Audit writer** (`app/audit.py`, `routers/audit.py`): `record(...)` in the caller's transaction, `GET /audit-events`, trigger and grant tests, import events hooked in. Checkpoint (1) with 5.0.
- Then in parallel:
  - **5b Resolution workflow** (`routers/exceptions.py`, `app/reconciliation/resolution.py`): state machine, `propose`/`approve`/`reject`/`reopen`, notes required where specified, version column with 409, reviewer cannot approve own proposal, audit events written. Checkpoint (2).
  - **5c Exports** (`routers/exports.py`): three streaming CSV endpoints, formula-injection-safe cells. Checkpoint (3).

Gate: API gate plus migration round trip. Required tests: full role matrix, stale-version 409, trigger rejects UPDATE and DELETE, export streaming does not load the whole result set.

Exit: audit trail covers imports and all four decisions; role rules hold.

### Phase 6 — Dashboard and UX

Goal: a new user completes the whole workflow unaided.

- **6.0 Foundation** (one agent): generated typed client (`openapi-typescript` plus `openapi-fetch`, `bun run gen:api` reading `backend/openapi.json`, checked by `contract.yml`), auth shell (login with Google button and demo login, CSRF handling, API base URL), and a small read-only workspace summary endpoint for dashboard counts. Checkpoint (1).
- Then in parallel, one route directory each:
  - **6a Workspaces and import wizard**: upload straight to the API origin, mapping, preview, polling of batch status.
  - **6b Dashboard**: import health, match rate, outstanding exceptions, batch history. Checkpoint (2) with 6a.
  - **6c Exception queue and detail**: filters, search, resolution actions with 409 handling. Checkpoint (3).
- **6d States and accessibility pass**: loading, empty, error, retry; labelled forms; keyboard use; responsive layouts. Checkpoint (4).

Gate: web gate, API gate, client drift gate.

Exit: the end-to-end workflow works from the UI against a local API.

### Phase 7 — Production readiness

Goal: key failure modes have reproducible tests and documented recovery.

Parallel slices:
- **7a Security**: rate limiting on auth and expensive endpoints, log redaction, security review written into `docs/security.md`, fixes for anything found. Checkpoint (1).
- **7b Observability**: `/health`, import duration, rows per second, match rate and exception rate emitted as structured log fields (no metrics service). Checkpoint (2).
- **7c E2E** (`frontend/e2e/`, `e2e.yml`): exactly three Playwright flows from section 11, using the seeded demo login. Checkpoint (3).
- **7d Operations**: `pg_dump` script and a tested restore, incident notes, `backend/scripts/benchmark.py` and measured numbers. Checkpoint (4).

Gate: API gate, web gate, Playwright against the local stack, restore test run once.

Exit: failure paths tested; recovery steps written and exercised.

### Phase 8 — Release pipeline and live deployment

Goal: a change moves from PR to staging through documented automation.

- **8a Seed and demo login** (`backend/scripts/seed_demo.py`, login-page demo reviewer credentials). Checkpoint (1).
- **8b Deploy config** (one `backend/Dockerfile`, a Render service file and a Cloud Run deploy script, `BACKEND_URL` for the Vercel rewrite, Vercel project settings, Neon pooled and direct URLs, migrations as a pre-deploy step only, the `/api/*` rewrite to Render, host-only cookie settings, and the 10 MB upload-through-rewrite check). Checkpoint (2).
- **8c Release workflow** (`.github/workflows/`): versioned images, staging deploy, migration, health check, Playwright smoke, deployment metadata. Folded into checkpoint (2) if small, otherwise checkpoint (3).
- **8d Docs** (`README.md`, architecture, API docs, trade-offs, limitations, screenshots, cold-start note). Final checkpoint.

Gate: all earlier gates, then a staging deploy run by the user, health check green, smoke tests green.

Exit: Definition of Done in section 14 is met for staging.

## 14. Definition of Done

- A live, usable application is deployed (staging; production optional).
- Core workflows are covered by unit, integration, and E2E tests.
- CI checks block broken changes.
- Staging deployment works; controlled production release works if budget allows.
- Duplicate imports and import retries are safe.
- Tenant isolation is tested.
- Matching decisions are explainable and reproducible.
- Logs, health checks, manual `pg_dump` restore instructions, and recovery instructions exist.
- README includes setup, architecture, trade-offs, limitations, screenshots, demo instructions, and the free-tier cold-start note.
- Performance claims include the dataset size, environment, method, and measured result.
- Architecture diagram (Mermaid) and a 2-minute walkthrough video are included; the demo reviewer login is shown on the staging login page.

## 15. Interview Preparation

Be ready to explain:

- Why store money as `NUMERIC(19,4)` with a currency code and use `Decimal` everywhere, instead of floating-point or integer minor units.
- How import idempotency works across HTTP requests without background jobs (file checksum, `Idempotency-Key` header, resume from `rows_processed`, chunks of 1,000 each in its own transaction).
- What happens if the import process crashes mid-file (per-chunk transactions; `rows_processed` is committed per chunk; resume skips committed row numbers).
- How duplicate matches are avoided under concurrent requests (unique match constraints plus optimistic versioning; 409 on stale version).
- How ambiguous candidates are handled (they stay ambiguous; they are never guessed).
- How tenant isolation is enforced and tested (non-null indexed `organization_id` on every tenant table; API-level cross-tenant denial tests).
- How to process a file much larger than available memory (streaming CSV parse; chunks of 1,000; the CLI path `python -m app.cli import <file>` with no row cap above the 10 MB / 50,000-row web limit).
- How sessions and CSRF are handled (PostgreSQL `sessions` table; HttpOnly Secure SameSite=Lax cookie; double-submit `X-CSRF-Token`).
- Who can approve what (role matrix; a reviewer cannot approve their own proposal).
- How to evolve the schema without downtime (Alembic; `alembic upgrade head` as a pre-deploy step on Render, never at app startup).
- What metrics reveal that the system is falling behind (import duration, rows/second, match rate, exception rate).
- Why Google sign-in uses OIDC with PKCE and a `state` parameter, and why only verified emails can link to existing accounts.
- What would you change at 10x volume?

Build the smallest correct version first. Add complexity only when a concrete requirement or measured bottleneck justifies it.
