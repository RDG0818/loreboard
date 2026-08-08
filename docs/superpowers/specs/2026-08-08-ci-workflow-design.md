# CI workflow (test + build gate) — design spec

Date: 2026-08-08
Status: approved, pending implementation plan

## Context

First item picked off `FUTURE_IMPROVEMENTS.md`'s "Production-readiness
gaps" list: "nothing gates PRs today except the ingest cron." Scoped as a
quick sweep, not a full CI/CD platform build-out.

## Goals

- Every PR (and push to `main`) automatically runs the backend test suite
  and the frontend production build, surfaced as GitHub PR checks.
- No new dependencies, no new test infrastructure — reuses `pytest
  backend` and `npx vite build` exactly as run manually throughout this
  session.

## Non-goals

- **No CD / deploy step.** No real hosting target exists yet (self-hosted
  Postgres is a placeholder; Supabase/Vercel replatform is unscoped in
  `FUTURE_IMPROVEMENTS.md`). A deploy stage would push to nothing real.
- **No linter.** No eslint/ruff/flake8 config exists anywhere in the repo
  today; adding one means picking a tool, writing a config, and likely
  fixing whatever it flags — real scope creep for a quick sweep. Flagged
  as a natural fast-follow, not built here.
- **No dependency vulnerability scanning step.** GitHub's Dependabot
  alerts (repo Settings → Security) cover this for free with zero
  workflow code — a manual toggle for the user, not something buildable
  from this environment (no `gh` CLI installed here, and it's a
  repo-settings change regardless of tooling).
- **No branch-protection / required-status-check configuration.** Also a
  repo-settings change, not a workflow-file change. Flagged as a manual
  follow-up for the user (see Open items).

## Decisions

**Separate workflow file, not folded into `data_pipeline.yml`.** Different
trigger (PR/push vs. daily cron + manual dispatch) and different purpose
(gate vs. ingest) — keeping them separate avoids a PR run accidentally
being gated on cron-only concerns or vice versa.

**Two independent parallel jobs, no `needs` between them.** A backend
test failure shouldn't block the frontend build from reporting its own
status, and vice versa — independent signals are more useful than a
single pass/fail blob.

**No Postgres service container.** Confirmed by inspection: every test
under `backend/db/tests/` and `backend/services/tests/` uses
`unittest.mock.MagicMock` for DB connections — none open a real Postgres
connection. Verified locally (`.venv/bin/python -m pytest backend`, 85
passed) with no Postgres process listening at all. `backend/db/connection.py::get_connection`
and `backend/main.py`'s required env vars (`DATABASE_URL`,
`SESSION_SECRET_KEY`, `FRONTEND_ORIGIN`) are only read lazily inside
function bodies / at import of `backend.main` specifically — and the one
test module that imports `backend.main` (`backend/tests/test_main.py`)
already sets its own env vars per-test via `monkeypatch`. No workflow-level
env vars or secrets needed for the test job at all.

## Workflow: `.github/workflows/ci.yml`

- **Triggers**: `pull_request` (any branch), `push` to `main`.
- **Concurrency**: one run per PR/ref at a time — a new push cancels the
  previous in-flight run for the same ref, instead of both racing.
- **Job `backend-tests`** (`ubuntu-latest`):
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5`, `python-version: "3.11"` (matches
     `data_pipeline.yml`)
  3. `pip install -r backend/requirements.txt`
  4. `pytest backend`
- **Job `frontend-build`** (`ubuntu-latest`):
  1. `actions/checkout@v4`
  2. `actions/setup-node@v4`, `node-version: "20"`
  3. `npm ci`
  4. `npm run build`
- No artifacts retained, no deploy step — build output is discarded after
  the job completes. This is a gate, not a pipeline.

## Testing

- Verified locally before writing this spec: `pytest backend` → 85
  passed (one pre-existing unrelated failure,
  `test_missing_frontend_origin_raises_keyerror` — only reproduces when a
  local `.env` file is present and `load_dotenv()` re-populates the var
  the test just deleted; won't reproduce in CI since no `.env` file
  exists there, and out of scope for this spec regardless). `npx vite
  build` → clean.
- Real verification of the workflow itself happens by opening a PR and
  watching the two checks run — no local GitHub Actions runner (`act` or
  similar) available in this environment to dry-run it first.

## Open items for later

- **Branch protection**: once this workflow has run successfully at least
  once, the user should mark `backend-tests` and `frontend-build` as
  required status checks (repo Settings → Branches → branch protection
  rule for `main`) so the gate actually blocks merges, not just reports
  status. Not done as part of this spec — needs `gh` CLI or manual UI
  action outside this environment.
- **Dependabot**: toggle on in repo Settings → Security — same
  "manual, outside this environment" situation as branch protection.
- **Lint, vuln-scan step, containerization, CD**: all separately deferred,
  see `FUTURE_IMPROVEMENTS.md`.
