# Secrets config + DB migrations — design spec

Date: 2026-08-07
Status: approved, pending implementation plan

## Context

Follow-up to the 2026-08 codebase-cleanup sweep. During a "what would it
take to make this production-ready" discussion, two items were flagged as
critical to do before any further feature work (see
`FUTURE_IMPROVEMENTS.md`, "Production-readiness gaps"):

1. `FRONTEND_ORIGIN` still has a dev-only default, unlike every other
   required credential.
2. Schema changes are applied via a single `SCHEMA_SQL` blob
   (`backend/db/connection.py`) using `CREATE TABLE IF NOT EXISTS` /
   `ADD COLUMN IF NOT EXISTS` — safe only for purely additive changes.
   Getting ahead of the first non-additive change (rename, type change,
   `NOT NULL` backfill, drop) before it's needed.

Everything else on the production-readiness list (CI, containerization,
pooling, observability) scales with load/traffic and is explicitly
deferred — this spec covers only the two items called out as blocking
regardless of traffic.

## Goals

- `FRONTEND_ORIGIN` fails fast on boot if unset, matching the existing
  pattern for `SESSION_SECRET_KEY` and `DATABASE_URL`.
- New-contributor/environment setup has a documented list of required env
  vars (`.env.example`).
- Schema changes go through versioned, ordered migrations with history and
  rollback, instead of a hand-maintained idempotent blob.
- The existing schema (as captured by today's `SCHEMA_SQL`) becomes the
  migration baseline — no schema drift introduced by this change.

## Non-goals

- No new schema changes in this pass — pure tooling swap, same schema
  before and after.
- No auto-apply-on-boot migration runner (see Decision: apply timing below)
  — that's explicitly deferred until/unless multi-instance deploy is real
  (tracked separately under the distributed-systems learning track in
  `FUTURE_IMPROVEMENTS.md`).
- No CI test/lint workflow, containerization, pooling, or observability —
  separate, already-deferred items.

## Decisions

**Migration tool: Alembic.** Considered a lightweight custom runner
(numbered `.sql` files + a `schema_migrations` table) as a lower-dependency
alternative that would better match the project's existing no-ORM, raw-SQL
style. Chose Alembic anyway: it doesn't require adopting the SQLAlchemy
ORM (works fine driving raw SQL/psycopg2), and battle-tested
rollback/history/branching tooling outweighs the one new dependency for
infra meant to be a permanent fixture, not a throwaway script.

**SCHEMA_SQL fate: retired, not kept alongside.** `SCHEMA_SQL` and
`init_schema()` are deleted entirely once migration `0001` captures the
same DDL. Considered keeping both (Alembic for new changes, `init_schema`
for fresh-DB bootstrap/tests) — rejected because it reintroduces exactly
the "two sources of truth for schema" problem this change exists to fix.

**Apply timing: explicit step, not auto-apply-on-boot.** `alembic upgrade
head` becomes something an operator/CI step runs deliberately, not
something the app or ingest job runs implicitly on every start. Matches
real production migration workflows, and avoids the concurrent-migration
race that auto-apply-on-boot would risk once more than one instance could
start at once (a gap already flagged in `FUTURE_IMPROVEMENTS.md`'s
distributed-systems section). The one automated consumer of schema today —
the daily ingest cron (`.github/workflows/data_pipeline.yml`) — gets an
explicit `alembic upgrade head` step added ahead of the pipeline run, so
the automated path stays equivalent to today's behavior, just visible in
the workflow file instead of implicit in `ingest/run.py`.

## Section A: Secrets/config hardening

- `backend/main.py:18` — `FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")`
  becomes `os.environ["FRONTEND_ORIGIN"]`. `SESSION_SECRET_KEY` and
  `DATABASE_URL` already follow this required-env-var pattern; this makes
  all three consistent.
- New `.env.example` at repo root: `GOOGLE_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`,
  `GOOGLE_OAUTH_CLIENT_SECRET`, `DATABASE_URL`, `SESSION_SECRET_KEY`,
  `FRONTEND_ORIGIN` — each with a one-line comment, no real values.
- `backend/tests/test_main.py` — add
  `monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")`
  alongside the existing `SESSION_SECRET_KEY` monkeypatch, since the app
  now fails to import without it.

## Section B: Alembic migrations

- Add `alembic` to `backend/requirements.txt`.
- Standard Alembic layout at `backend/db/migrations/` (`env.py`,
  `versions/`), configured to read `DATABASE_URL` from the existing env
  var rather than a separate credential in `alembic.ini`.
- Migration `0001` = today's `SCHEMA_SQL` verbatim, as the upgrade step
  (baseline — captures exactly what's already deployed, nothing more). The
  `pg_trgm` extension creation and all `CREATE TABLE`/`ALTER TABLE`/`CREATE
  INDEX` statements currently in `SCHEMA_SQL` move here unchanged.
- Delete `SCHEMA_SQL` and `init_schema()` from `backend/db/connection.py`.
  `CREATE_EXTENSION_SQL` (`CREATE EXTENSION IF NOT EXISTS vector`, run
  inside `get_connection()`) stays — it's a per-connection bootstrap need
  (register_vector's OID lookup) unrelated to table schema, not something
  Alembic should own.
- Remove the `db.init_schema(conn)` call from `backend/ingest/run.py`
  (currently line 82).
- Add an `alembic upgrade head` step to
  `.github/workflows/data_pipeline.yml`, before the "Run pipeline" step,
  with `DATABASE_URL` in its env (already available as a repo secret).
- `backend/db/tests/test_connection.py` —
  `test_init_schema_creates_expected_tables` deleted (tests deleted code);
  `test_get_connection_creates_extension_before_registering_vector` stays
  unchanged.
- README: new "Database migrations" section — `alembic revision -m "..."`
  to create a migration, `alembic upgrade head` to apply; note that fresh
  local setup now requires running that once before first use (previously
  implicit via `init_schema`).

## Testing

- No existing test hits a real Postgres instance — all `backend/db/tests/`
  coverage uses `MagicMock` connections. This spec doesn't change that
  pattern; Alembic's own migration correctness is verified manually
  (`alembic upgrade head` against a real local DB) rather than via a new
  integration-test harness, consistent with how the rest of the DB layer
  is tested today.
- `backend/tests/test_main.py` (route-registration smoke test) updated per
  Section A and re-verified to still pass.

## Open items for later

- `auth_router.auth_callback` / `services/auth.py`'s `get_current_user`
  still hand-roll `get_connection()` instead of `Depends(get_db)` — noted
  in the prior cleanup-sweep handoff, unrelated to this spec, not touched
  here.
- Auto-apply-on-boot migrations, if multi-instance deploy ever happens —
  tracked under the distributed-systems learning-track idea in
  `FUTURE_IMPROVEMENTS.md`.
