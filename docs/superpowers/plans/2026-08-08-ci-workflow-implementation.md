# CI Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions workflow that runs the backend test suite and the frontend production build on every PR and every push to `main`, so PRs get automated pass/fail signal instead of nothing.

**Architecture:** One new workflow file, `.github/workflows/ci.yml`, with two independent parallel jobs (`backend-tests`, `frontend-build`) and no shared state between them. Separate from the existing `data_pipeline.yml` (different trigger, different purpose).

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`), pytest, Vite — all already in use elsewhere in this repo, no new dependencies.

## Global Constraints

- Python version: `3.11` (matches `.github/workflows/data_pipeline.yml`).
- Node version: `20`.
- No Postgres service container — confirmed in the spec that the full backend suite runs against `MagicMock` connections only.
- No env vars/secrets needed for either job.
- No deploy step, no artifact retention, no lint step, no vuln-scan step (all explicit non-goals in `docs/superpowers/specs/2026-08-08-ci-workflow-design.md`).

---

### Task 1: Add the CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `backend/requirements.txt` (existing, unmodified), `package.json`'s `build` script (existing, unmodified — `vite build`).
- Produces: two GitHub Actions job names, `backend-tests` and `frontend-build`, that will appear as PR status checks once this workflow runs on a real PR. Nothing later in this repo depends on these names programmatically — they're referenced here only so a human setting up branch protection (out of scope, see spec's "Open items") knows what to select.

- [ ] **Step 1: Write the workflow file**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r backend/requirements.txt

      - name: Run tests
        run: pytest backend

  frontend-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build
```

- [ ] **Step 2: Validate the YAML parses**

Run: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "valid YAML"`

Expected: `valid YAML` printed, no exception. (Catches indentation/syntax mistakes before they only surface on GitHub's side.)

- [ ] **Step 3: Verify the backend job's exact commands succeed locally**

Run, from repo root, using the project's existing venv:

```bash
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pytest backend
```

Expected: dependency install succeeds (already-satisfied is fine — this venv already has them, confirming the requirements file is complete and correct on its own), and `pytest backend` reports all tests passing except the one pre-existing unrelated failure already documented in the spec (`test_missing_frontend_origin_raises_keyerror`, an artifact of a local `.env` file that won't exist in CI).

- [ ] **Step 4: Verify the frontend job's exact commands succeed locally**

Run, from repo root:

```bash
npm ci
npm run build
```

Expected: clean install, `vite build` completes with no errors (matches every `npx vite build` run earlier this session).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: add PR/push test+build gate

Runs pytest (backend) and vite build (frontend) as two independent jobs
on every PR and push to main. No deploy step, no lint, no vuln scan —
see docs/superpowers/specs/2026-08-08-ci-workflow-design.md for the full
scope decisions and why each was deferred.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage**: workflow file (✓ Task 1), two independent parallel jobs with no `needs` (✓, no `needs` key present), correct triggers (✓ `pull_request` + `push: branches: [main]`), concurrency cancellation (✓), Python 3.11 / Node 20 (✓), no env vars/secrets (✓, none declared), no deploy/lint/vuln-scan/artifact steps (✓, none present). Branch protection and Dependabot are explicitly out of scope in the spec (manual, repo-settings, outside this environment) — correctly not tasked here.
- **Placeholder scan**: none — every step has literal file content or an exact runnable command.
- **Single-task plan**: this sweep produces exactly one artifact (one YAML file with no code dependencies elsewhere in the repo), so one task is correctly sized — splitting further would just fragment one file's creation across artificial boundaries.
