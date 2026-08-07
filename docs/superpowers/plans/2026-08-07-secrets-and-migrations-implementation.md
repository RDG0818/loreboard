# Secrets config + DB migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `FRONTEND_ORIGIN` fail fast like every other required credential, and replace the hand-maintained `SCHEMA_SQL` blob with versioned Alembic migrations, without changing the deployed schema.

**Architecture:** Two independent pieces. (1) Delete `FRONTEND_ORIGIN`'s dev-only default in `backend/main.py`, add `.env.example`. (2) Add Alembic scaffolding under `backend/db/migrations/`, write one baseline migration (`0001`) that wraps today's `SCHEMA_SQL` verbatim, then delete `SCHEMA_SQL`/`init_schema()` and wire `alembic upgrade head` into the one automated consumer of schema (`.github/workflows/data_pipeline.yml`).

**Tech Stack:** Python 3, FastAPI, psycopg2, Alembic (pulls in SQLAlchemy as a transitive dependency — used only to drive migration execution, no ORM models). pytest for backend tests. Project venv at `.venv/`.

## Global Constraints

- Migration tool is Alembic — not a custom `.sql`-file runner (spec decision).
- `SCHEMA_SQL` and `init_schema()` are fully retired once the baseline migration lands — not kept alongside Alembic (spec decision).
- Schema application is an explicit step (`alembic upgrade head`), never auto-applied on app/ingest boot (spec decision).
- `FRONTEND_ORIGIN` must fail fast (`os.environ[...]`, no default) — matches existing `SESSION_SECRET_KEY`/`DATABASE_URL` pattern.
- No schema changes in this pass — migration `0001` must be byte-for-byte the same DDL as today's `SCHEMA_SQL`.
- Out of scope: CI test/lint workflow, containerization, DB pooling, observability — separate, already-deferred work.
- Full spec: `docs/superpowers/specs/2026-08-07-secrets-and-migrations-design.md`.

---

### Task 1: FRONTEND_ORIGIN fail-fast + .env.example

**Files:**
- Modify: `backend/main.py:18`
- Modify: `backend/tests/test_main.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on — fully independent of Task 2/3.

- [ ] **Step 1: Write the failing test**

Replace the full contents of `backend/tests/test_main.py` with:

```python
import importlib
import sys

import pytest


def test_missing_frontend_origin_raises_keyerror(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    sys.modules.pop("backend.main", None)

    with pytest.raises(KeyError):
        importlib.import_module("backend.main")


def test_app_exposes_expected_routes(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")
    from backend.main import app

    # FastAPI >=0.141 stores included routers as lazy `_IncludedRouter`
    # wrappers on `app.routes`, so a plain `route.path` walk only sees the
    # four auto-added docs/openapi routes. `app.openapi()["paths"]` forces
    # resolution and reflects the actual mounted routes.
    paths = set(app.openapi()["paths"].keys())

    assert "/api/v1/cards" in paths
    assert "/api/v1/cards/search" in paths
    assert "/api/v1/cards/{card_id}" in paths
    assert "/api/v1/cards/{card_id}/similar" in paths
    assert "/api/v1/recommendations" in paths
    assert "/api/v1/saves" in paths
    assert "/api/v1/saves/{card_id}" in paths
    assert "/api/v1/search/natural" in paths
    assert "/api/v1/views" in paths
    assert "/auth/login/google" in paths
    assert "/auth/callback" in paths
    assert "/api/v1/me" in paths
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate && python -m pytest backend/tests/test_main.py -v
```

Expected: `test_missing_frontend_origin_raises_keyerror` FAILS (`DID NOT RAISE <class 'KeyError'>`) — current code has a default, so import succeeds. `test_app_exposes_expected_routes` still PASSES (the new `setenv` line doesn't break anything yet).

- [ ] **Step 3: Remove the default**

In `backend/main.py`, change line 18:

```python
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
```

to:

```python
FRONTEND_ORIGIN = os.environ["FRONTEND_ORIGIN"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest backend/tests/test_main.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Add `.env.example`**

Create `.env.example` at the repo root:

```
# Google Gemini API key — used for NL search translation and embeddings
# (backend/services/nl_search.py, backend/ingest/embed.py)
GOOGLE_API_KEY=

# Google OAuth app credentials — used for sign-in (backend/routers/auth_router.py)
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=

# Postgres connection string, e.g. postgresql://user:password@host:port/dbname
DATABASE_URL=

# Random secret used to sign session cookies, e.g. `openssl rand -hex 32`
SESSION_SECRET_KEY=

# Origin the frontend is served from, used for CORS, e.g. http://localhost:5173 in dev
FRONTEND_ORIGIN=
```

- [ ] **Step 6: Run the full backend test suite**

```bash
source .venv/bin/activate && python -m pytest backend/ -q
```

Expected: `87 passed` (86 existing + 1 new).

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_main.py .env.example
git commit -m "fix: require FRONTEND_ORIGIN, drop dev-only default

Matches the existing fail-fast pattern for SESSION_SECRET_KEY/
DATABASE_URL — a missing env var now crashes loudly on boot instead of
silently misconfiguring CORS in prod. Adds .env.example listing all
required vars."
```

---

### Task 2: Alembic scaffolding + baseline migration

**Files:**
- Modify: `backend/requirements.txt`
- Create: `alembic.ini`
- Create: `backend/db/migrations/env.py`
- Create: `backend/db/migrations/script.py.mako`
- Create: `backend/db/migrations/versions/0001_baseline_schema.py`

**Interfaces:**
- Consumes: `DATABASE_URL` env var (already required, same as `backend/db/connection.py`).
- Produces: a working `alembic upgrade head` command that Task 3 wires into CI. Revision id `"0001"` is the head after this task — Task 3 does not add further revisions, just removes the code this migration replaces.

This task is purely additive — nothing existing is deleted yet, so it's safe to verify independently before Task 3 removes the old path.

- [ ] **Step 1: Add alembic to requirements**

Append to `backend/requirements.txt`:

```
alembic
```

Install it:

```bash
source .venv/bin/activate && pip install -r backend/requirements.txt
```

Expected: `alembic` and `sqlalchemy` (its transitive dependency) install successfully.

- [ ] **Step 2: Create `alembic.ini`**

Create `alembic.ini` at the repo root:

```ini
[alembic]
script_location = backend/db/migrations
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

No `sqlalchemy.url` line here on purpose — `env.py` sets it from `DATABASE_URL` at runtime (Task's whole point: one source of truth for the DB URL, matching how `backend/db/connection.py` already reads it).

- [ ] **Step 3: Create `backend/db/migrations/env.py`**

```python
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`target_metadata = None` is deliberate — this project has no SQLAlchemy ORM models (raw SQL via psycopg2 everywhere else), so there's nothing for Alembic's autogenerate to diff against. Migrations are written by hand as raw SQL (see Step 5).

- [ ] **Step 4: Create `backend/db/migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

This is Alembic's standard template, used by `alembic revision` for every migration created after this one.

- [ ] **Step 5: Create the baseline migration**

Create `backend/db/migrations/versions/0001_baseline_schema.py`. The `SCHEMA_SQL` string below is copied verbatim from `backend/db/connection.py` (Task 3 deletes it from there) — no changes to the DDL:

```python
"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-08-07

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    oracle_text TEXT,
    type_line TEXT,
    mana_cost TEXT,
    cmc REAL,
    colors TEXT[],
    color_identity TEXT[],
    legalities JSONB,
    artist TEXT,
    image_uris JSONB,
    embedding vector(768),
    set_type TEXT,
    is_universes_beyond BOOLEAN NOT NULL DEFAULT FALSE
);

-- ADD COLUMN IF NOT EXISTS for databases that already had a `cards` table
-- before these columns existed (CREATE TABLE IF NOT EXISTS above is a no-op
-- on those, since the table already exists).
ALTER TABLE cards ADD COLUMN IF NOT EXISTS set_type TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS is_universes_beyond BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS cards_embedding_hnsw_idx ON cards USING hnsw (embedding vector_cosine_ops);

-- gin_trgm_ops speeds up the ILIKE '%word%' scans in query_parser.py (name/
-- oracle_text/type_line lookups) — a plain B-tree can't help a leading-
-- wildcard match, trigram indexing can.
CREATE INDEX IF NOT EXISTS cards_name_trgm_idx ON cards USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cards_oracle_text_trgm_idx ON cards USING gin (oracle_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cards_type_line_trgm_idx ON cards USING gin (type_line gin_trgm_ops);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saves (
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_id TEXT NOT NULL REFERENCES cards(id),
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, card_id)
);

CREATE TABLE IF NOT EXISTS views (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_id TEXT NOT NULL REFERENCES cards(id),
    viewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cards_type_line_trgm_idx;")
    op.execute("DROP INDEX IF EXISTS cards_oracle_text_trgm_idx;")
    op.execute("DROP INDEX IF EXISTS cards_name_trgm_idx;")
    op.execute("DROP INDEX IF EXISTS cards_embedding_hnsw_idx;")
    op.execute("DROP TABLE IF EXISTS views;")
    op.execute("DROP TABLE IF EXISTS saves;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TABLE IF EXISTS cards;")
```

- [ ] **Step 6: Verify against the local Postgres instance**

The repo's `.env` already has `DATABASE_URL` pointing at a running local `pgvector/pgvector:pg16` container (`docker ps` shows it as `loreboard-pg`, port 5433). Run:

```bash
source .venv/bin/activate && set -a && source .env && set +a && alembic upgrade head
```

Expected: `Running upgrade  -> 0001, baseline schema` (or similar), exit code 0. Safe to run even if these tables already exist from prior manual `init_schema()` runs — every statement in `SCHEMA_SQL` is `IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS`.

Then confirm Alembic recorded it:

```bash
source .venv/bin/activate && set -a && source .env && set +a && alembic current
```

Expected: `0001 (head)`.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt alembic.ini backend/db/migrations
git commit -m "feat: add Alembic scaffolding + baseline migration

Migration 0001 wraps today's SCHEMA_SQL verbatim, captured as the
baseline before any old code is removed. Purely additive — nothing
existing changes yet."
```

---

### Task 3: Retire SCHEMA_SQL/init_schema, wire CI, document

**Files:**
- Modify: `backend/db/connection.py`
- Modify: `backend/db/tests/test_connection.py`
- Modify: `backend/ingest/run.py`
- Modify: `.github/workflows/data_pipeline.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `alembic upgrade head` from Task 2 (must already work before this task removes the code it replaces).
- Produces: nothing further downstream — this is the last task in the plan.

- [ ] **Step 1: Delete the test for the code about to be removed**

In `backend/db/tests/test_connection.py`, delete `test_init_schema_creates_expected_tables` (lines 5–14 in the current file) entirely. `test_get_connection_creates_extension_before_registering_vector` stays unchanged.

- [ ] **Step 2: Remove `SCHEMA_SQL` and `init_schema()` from `backend/db/connection.py`**

Delete the `SCHEMA_SQL = """..."""` block (lines 8–63) and the `init_schema()` function (lines 80–83). `CREATE_EXTENSION_SQL` and `get_connection()` are untouched — the `vector` extension bootstrap inside `get_connection()` is unrelated to table schema and stays exactly as-is. Resulting file:

```python
import os

import psycopg2
from pgvector.psycopg2 import register_vector

CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"


def get_connection():
    """Connects to Postgres using DATABASE_URL. Ensures the `vector` extension
    exists before calling register_vector — register_vector looks up the
    `vector` type's OID, which fails on a completely fresh database where the
    extension hasn't been created yet (init_schema normally creates it, but
    that runs after get_connection, so the bootstrap step must happen here)."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with conn.cursor() as cur:
        cur.execute(CREATE_EXTENSION_SQL)
    conn.commit()
    register_vector(conn)
    return conn


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
```

Note: the docstring's `init_schema` reference is now stale (`init_schema` no longer exists) — update the parenthetical to: `(a migration normally creates it via 'alembic upgrade head', but that runs independently of get_connection, so the bootstrap step must happen here)`.

- [ ] **Step 3: Remove the `init_schema` call from the ingest pipeline**

In `backend/ingest/run.py`, change `run()` (currently lines 78–88) from:

```python
def run() -> None:
    cfg = load_config()
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        ingested = ingest_cards(conn)
        print(f"Ingested/updated {ingested} cards.")
        embedded = backfill_embeddings(conn, cfg)
        print(f"Embedded {embedded} cards.")
    finally:
        conn.close()
```

to:

```python
def run() -> None:
    cfg = load_config()
    conn = db.get_connection()
    try:
        ingested = ingest_cards(conn)
        print(f"Ingested/updated {ingested} cards.")
        embedded = backfill_embeddings(conn, cfg)
        print(f"Embedded {embedded} cards.")
    finally:
        conn.close()
```

- [ ] **Step 4: Run the backend test suite**

```bash
source .venv/bin/activate && python -m pytest backend/ -q
```

Expected: `87 passed` (same count as after Task 1 — one test deleted in Step 1, but nothing added here since `run()` had no test coverage of the `init_schema` call to begin with).

- [ ] **Step 5: Wire the CI workflow**

In `.github/workflows/data_pipeline.yml`, add a step before "Run pipeline" (after "Install dependencies"):

```yaml
      - name: Apply DB migrations
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: alembic upgrade head

      - name: Run pipeline
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: python -m backend.ingest.run
```

Full resulting file:

```yaml
# .github/workflows/data_pipeline.yml
name: Data Pipeline

on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch: {}

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r backend/requirements.txt

      - name: Apply DB migrations
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: alembic upgrade head

      - name: Run pipeline
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: python -m backend.ingest.run
```

- [ ] **Step 6: Document migrations in the README**

Add a new section to `README.md`, after "## Core Features/Technical Stack" and before "## Future Development":

```markdown
## Database Migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/) (`backend/db/migrations/`). `DATABASE_URL` is read the same way the app reads it (env var) — no separate credential in `alembic.ini`.

- Apply all pending migrations: `alembic upgrade head`
- Create a new migration: `alembic revision -m "describe the change"`, then hand-write the SQL in the generated file's `upgrade()`/`downgrade()`.

Fresh local setup requires running `alembic upgrade head` once before first use — the app and ingest pipeline no longer apply schema automatically.
```

- [ ] **Step 7: Verify `alembic upgrade head` is a clean no-op post-removal**

```bash
source .venv/bin/activate && set -a && source .env && set +a && alembic upgrade head
```

Expected: no new output beyond Alembic's own logging (already at `0001`, nothing to apply) — confirms removing `init_schema()` didn't orphan the schema-application path.

- [ ] **Step 8: Commit**

```bash
git add backend/db/connection.py backend/db/tests/test_connection.py backend/ingest/run.py .github/workflows/data_pipeline.yml README.md
git commit -m "refactor: retire SCHEMA_SQL/init_schema in favor of Alembic

Schema application is now alembic upgrade head, run explicitly (CI
step in data_pipeline.yml for the automated path) rather than
implicitly on every ingest run. SCHEMA_SQL's DDL is unchanged — it
now lives in migration 0001 (Task 2) instead of connection.py."
```

---

## Final verification

After all three tasks:

```bash
source .venv/bin/activate && python -m pytest backend/ -q
```

Expected: `87 passed`.

```bash
source .venv/bin/activate && cd /home/ryan/Repos/loreboard && npx vite build
```

Expected: clean build, unaffected by backend-only changes (sanity check, not required by this plan's scope).
