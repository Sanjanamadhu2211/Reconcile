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

- **Frontend:** Next.js + TypeScript
- **Backend API:** Python + FastAPI
- **ORM and migrations:** SQLAlchemy + Alembic
- **Database:** PostgreSQL
- **Validation:** FastAPI's built-in request validation and Pydantic models.
- **Unit/integration tests:** Pytest
- **Browser tests:** Playwright
- **Local infrastructure:** Docker Compose
- **CI/CD:** GitHub Actions
- **Deployment:** Docker-compatible app hosting plus managed PostgreSQL
- **Observability:** structured JSON logs with request IDs, a health endpoint, and Sentry error tracking.

Use a modular monolith: API and web are separate processes from the same codebase (no worker process). Do not introduce microservices for the MVP.

## 5. Key Design Decisions

- Synchronous bounded imports: one HTTP request per CSV file (max 10 MB, 50,000 rows), rows committed in chunks of 1,000 with each chunk in its own transaction, status kept in `import_batches`; a CLI path (`python -m app.cli import <file>`) reuses the same code with no row cap for larger files.
- NUMERIC money: amounts stored as PostgreSQL `NUMERIC(19,4)` with a 3-letter ISO 4217 currency code; Python `Decimal` throughout; decimal strings sent and received over the API.
- Idempotency by checksum: unique (`workspace_id`, `file_checksum`) on `import_batches`; completed batches are returned as-is, failed or stuck batches resume from `rows_processed` skipping committed row numbers; an `Idempotency-Key` header on `POST /imports` maps to the same batch.
- Tenant isolation by `organization_id`: every tenant table carries a non-null, indexed `organization_id` foreign key, and every API access is authorized.
- DB-enforced append-only audit: the application DB role has only INSERT and SELECT on `audit_events`, plus a trigger that raises on UPDATE or DELETE.
- Session cookie auth with CSRF: email/password OR Google sign-in, server-side PostgreSQL `sessions` table, HttpOnly Secure SameSite=Lax cookie, double-submit `X-CSRF-Token`.
- Two-step resolution: exception state machine open → proposed → resolved/open, with an optimistic version column (stale updates return 409).
- Split domains for deployment: frontend on Vercel at `app.<domain>`, API on Render at `api.<domain>`, cookie Domain on the parent domain, CORS limited to the exact web origin with credentials; uploads go from the browser directly to the API origin.

ADRs to create under `docs/adr/` (one per bullet above):

- `0001-synchronous-bounded-imports.md`
- `0002-numeric-money.md`
- `0003-idempotency-by-checksum.md`
- `0004-tenant-isolation-by-organization-id.md`
- `0005-append-only-audit.md`
- `0006-session-cookie-auth-with-csrf.md`
- `0007-two-step-resolution.md`
- `0008-split-domains-for-deployment.md`
- `0009-google-sign-in-plus-password-login.md`

## 6. Proposed Repository Structure

```text
reconcile/
├── web/                      # Next.js + TypeScript dashboard
│   ├── src/lib/api/          # Typed client (openapi-typescript + openapi-fetch) generated from /openapi.json via npm script
│   └── e2e/                  # Playwright E2E tests (exactly 3 flows)
├── api/                      # Python + FastAPI REST API
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
│   ├── scripts/              # seed_demo.py, benchmark.py
│   ├── tests/                # Pytest suites and fixtures
│   └── pyproject.toml
├── docs/
│   ├── architecture.md       # incl. Mermaid architecture diagram
│   ├── data-model.md
│   ├── security.md
│   └── adr/                  # one ADR per Key Design Decisions bullet
├── .github/workflows/
├── docker-compose.yml
├── .env.example
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
- Register the redirect URI separately for local and staging (and production if used) in Google Cloud Console. The OAuth consent screen uses the External user type.

### Environment variables

See `.env.example`: `DATABASE_URL`, `DATABASE_DIRECT_URL`, `SESSION_SECRET`, `CORS_ORIGIN`, `COOKIE_DOMAIN`, `SENTRY_DSN`, `MAX_UPLOAD_MB`, `MAX_IMPORT_ROWS`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.

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
- E2E smoke suite against staging.
- Test the failure paths, not only the happy path.
- The performance suite is one benchmark script, `api/scripts/benchmark.py`, which seeds 10k to 100k synthetic rows with a known match/exception ratio and records rows per second and match accuracy in the README.

## 12. CI/CD and Deployment

### Pull request workflow

1. Install dependencies from the lockfile and pyproject.toml.
2. Run formatting/lint checks and type checks (Ruff, Pytest with coverage, ESLint, `tsc`).
3. Run unit tests.
4. Start disposable PostgreSQL service for integration tests.
5. Run migrations and integration tests.
6. Build all deployable applications.
7. Run the OpenAPI client drift check (CI fails if the generated client is out of date).
8. Run dependency and secret scanning (pip-audit, gitleaks).
9. Require checks to pass before merge.

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
- Run backward-compatible migrations before application rollout (`alembic upgrade head` as a pre-deploy step on Render, never at app startup).
- Verify readiness and critical workflows.
- Maintain a rollback procedure and migration recovery notes.
- Never assume rolling back application code automatically rolls back a database migration.

### Operational requirements

- Deployment: frontend on Vercel; API as a Docker container on Render (Cloud Run is a documented equivalent alternative). Database on Neon free tier: pooled URL for the app, direct URL for Alembic.
- One custom domain: `app.<domain>` for the web app and `api.<domain>` for the API. Cookie Domain is set to the parent domain; CORS allows only the exact web origin with credentials.
- File uploads go from the browser directly to the API origin, never through Next.js (Vercel limits request bodies to about 4.5 MB).
- Single `/health` endpoint that also checks the database (no separate `/ready`).
- Structured JSON logs with request IDs; Sentry error tracking and alerts.
- Metrics for import duration, rows/second, match rate, exception rate.
- A documented manual `pg_dump` script plus Neon's built-in history (replaces scheduled backups); tested restore procedure.
- Separate staging and (optional) production secrets and data.
- DB pool: SQLAlchemy `pool_size=5`, `max_overflow=5`, `pool_pre_ping=True`; single uvicorn worker.
- Migrations: run `alembic upgrade head` as a pre-deploy step on Render, never at app startup.
- README note: free tiers cold-start after idle.
- Note: free-tier limits (Vercel body size, Render request timeout of roughly 100 s) are stated from memory and must be re-checked against current docs before launch.

## 13. Sequential Build Plan

### Milestone 0 — Define the contract

- Write a concise PRD and architecture diagram (Mermaid).
- Define CSV formats and canonical transaction schema.
- Create sample datasets containing exact matches, missing records, duplicates, refunds, fees, malformed rows, and ambiguous candidates.
- Document key invariants and ADRs.

**Exit criteria:** Requirements and fixtures make expected reconciliation results unambiguous.

### Milestone 1 — Repository and local environment

- Initialize the repo with `web/` and `api/`, linting and formatting (Ruff for Python, ESLint and Prettier for the frontend), and Pytest.
- Add Docker Compose for PostgreSQL.
- Add configuration validation and `.env.example`.
- Add a basic health endpoint and CI workflow.

**Exit criteria:** A fresh clone can start locally and pass CI.

### Milestone 2 — Identity and tenancy

- Implement authentication (email/password, argon2-cffi, PostgreSQL sessions, CSRF) and Google sign-in (OpenID Connect with PKCE, account linking, and sessions in the same table).
- Add organizations, memberships, and roles (analyst and reviewer only).
- Implement workspace CRUD and authorization.
- Add cross-tenant access tests.

**Exit criteria:** Users can only access authorized organization data.

### Milestone 3 — Import pipeline

- Implement upload, checksum, column mapping, preview, and validation.
- Persist import batches and row errors.
- Process imports synchronously (one HTTP request per file, chunks of 1,000).
- Add progress and failure reporting using `import_batches.status`; the browser polls `GET /imports/{id}`.

**Exit criteria:** Duplicate submission is safe, invalid rows are visible, imports resume from `rows_processed`, and the CLI path handles larger files with no row cap.

### Milestone 4 — Matching engine

- Implement canonical normalization and deterministic rules (exact external ID; amount plus currency within tolerance).
- Add match, unmatched, ambiguous, and exception classifications.
- Persist rule versions and the `rule` that produced each match.
- Add reproducibility and concurrency tests.

**Exit criteria:** Fixtures produce deterministic results and reruns do not duplicate outcomes.

### Milestone 5 — Review and audit

- Build discrepancy queue, filters, detail pages, and resolution workflow (propose, approve, reject, reopen).
- Add reviewer actions, optimistic versioning (409 on stale), and append-only audit events.
- Add the three streaming CSV export endpoints.

**Exit criteria:** Every resolution is attributable and explainable.

### Milestone 6 — Dashboard and UX

- Build import wizard, batch status, reconciliation summary, and exception views.
- Add loading, empty, error, and retry states.
- Add accessible forms and responsive layouts.

**Exit criteria:** A new user can complete the end-to-end workflow without developer intervention.

### Milestone 7 — Production readiness

- Add security review, rate limiting, redaction, health checks, metrics, and error tracking (Sentry).
- Add Playwright E2E tests (exactly three flows).
- Document backup/restore (manual `pg_dump`, Neon history) and incident response.

**Exit criteria:** Key failure modes have reproducible tests and documented recovery steps.

### Milestone 8 — Release pipeline and live deployment

- Deploy staging (production is optional, only if budget allows).
- Add protected release workflow; run migrations and smoke tests automatically.
- Seed a demo organization with `api/scripts/seed_demo.py`; show a demo reviewer login on the staging login page; both the Google sign-in button and demo login are available; reset by running the seed script by hand (no scheduler).
- Publish architecture (Mermaid diagram), API docs, demo credentials, and a 2-minute walkthrough video.

**Exit criteria:** A code change can move from PR to staging (and controlled production if budget allows) through documented automation.

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
