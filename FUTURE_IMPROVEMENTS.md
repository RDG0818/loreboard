# Future improvements

Deferred upgrade paths — simple version shipped now, here's the next lever
if it stops being enough. Not urgent, not scoped, just don't want to
forget the idea. Newest first.

## Production-readiness gaps

Logged 2026-08 after a "what would it take to make this a fully-serviced,
production-ready app" discussion — not scoped, not started, just the punch
list so it isn't re-derived from scratch later.

- **CI**: nothing gates PRs today except the ingest cron
  (`.github/workflows/data_pipeline.yml`). Need a test+lint+build workflow
  (pytest, frontend build, ideally a dependency vuln scan) before this
  grows much more.
- **Containerization**: no Dockerfile/compose — no repeatable build/deploy
  artifact yet.
- **DB connection pooling**: connection-per-request (see below, already
  flagged) won't survive real concurrent load.
- **DB migrations**: `SCHEMA_SQL` in `backend/db/connection.py` is a single
  blob, no versioned migration tool (Alembic or similar). Fine solo; risky
  once schema changes happen more than rarely.
- **Secrets/config**: `SESSION_SECRET_KEY`/`FRONTEND_ORIGIN` still have
  env-var defaults (already flagged under Replatform below) — a real gap,
  not just a placeholder, once anything is internet-facing for real.
- **Observability**: no structured logging, no error tracking (Sentry-class
  tool), no metrics (latency/error rate/DB pool saturation/Gemini
  cost+latency), no alerting.
- **Reliability**: no public-API rate limiting (only the Gemini calls are
  rate-limited internally, via `ingest/rate_limit.py`), no DB-layer
  retry/backoff (Gemini calls have this via `ingest/gemini_retry.py`, DB
  calls don't), no backup/restore story for Postgres.
- **Testing**: backend has pytest coverage, frontend has zero tests, no
  e2e/browser tests, no load testing.

Highest-leverage first pass if/when this gets picked up: CI gate, Dockerfile,
connection pooling, structured logging + error tracking.

## Learning-track ideas: distributed systems / agentic orchestration / rec-sys

User wants hands-on experience in these three areas specifically; logged
2026-08 as candidate projects that plug into *this* app rather than a
generic exercise, so they double as actual improvements when picked up.

- **Distributed systems**: DB pooling → multi-instance backend is the
  natural on-ramp. Add pgbouncer (or a pool lib) and run 2+ backend
  instances behind a load balancer — this immediately surfaces real
  problems: session affinity (or move sessions to a shared store like
  Redis), cache coherence (the in-process Gemini translation cache, see
  above, breaks across instances — forces a real fix instead of a
  deferred one), and the ingest cron becoming a leader-election problem
  once more than one instance could pick it up.
- **Agentic orchestration**: the NL search path
  (`backend/services/nl_search.py` + `query_parser.py`) is one Gemini
  call → one query today. Turn it into a small agent loop: a planner
  step that chooses structured-filter vs. semantic-vector vs. hybrid
  search, retry/refine on empty results, optionally a second call that
  explains *why* it picked the returned cards. The recommendations
  upgrade below is the other natural fit — orchestration only earns its
  keep once there's a real decision tree, not a single-shot call.
- **Recommendation systems**: current `compute_taste_vector` in
  `backend/services/recommendations.py` is a flat mean of saved-card
  embeddings — a real starting point, but shallow. Upgrade path: (1)
  weighted vector (recency/interaction-type weighted, not flat mean),
  (2) collaborative-filtering signal (users who saved X also saved Y)
  layered alongside the existing content-based embedding similarity —
  the classic hybrid rec-sys setup, (3) an offline eval loop
  (precision@k against held-out saves) so changes are measured, not
  eyeballed.

## Replatform: Supabase / Vercel

Current stack (self-hosted Postgres + pgvector, FastAPI on its own host,
static Vite frontend) is a placeholder — user intends to eventually move
onto Supabase (Postgres+pgvector already supported natively) and Vercel
(frontend hosting, possibly API too via serverless functions). Not
scoped, not started; flagged during the 2026-08 codebase cleanup sweep so
it isn't lost. Log any other placeholder-feeling infra choices spotted
during that sweep here too (e.g. `SESSION_SECRET_KEY`/`FRONTEND_ORIGIN`
env defaults, connection-per-request instead of pooling) rather than
fixing them inline.

## Gemini translation cache: in-process dict → DB-backed / shared cache

Current (`backend/services/nl_search.py`, `_translation_cache`) is a plain
in-process dict: resets on every restart, and doesn't share hits across
multiple backend instances if we ever run more than one. Fine for a
single-instance app; if that changes, upgrade to a small DB table
(`nl_query_cache(normalized_text PK, translated_query, created_at)`) or a
shared cache like Redis so the hit rate doesn't reset on deploy and scales
across instances.

## Gemini translation cache: exact-match → semantic/paraphrase match

Current cache only catches literal repeat text (normalized by
trim+lowercase). "cheap card draw" and "inexpensive draw spells" are
cache misses even though they'd translate to the same query. Real fix
would be embedding the request text and doing a nearest-neighbor lookup
against cached queries (we already have `pgvector` + embeddings in this
project for card search, so the infra exists) — worth it only if repeat
*paraphrased* searches turn out to be common enough to matter.

## Feed shuffle order (`md5(id || seed)`) has no supporting index

Flagged in `docs/notes/polish-backlog.md` — can't just add a normal
expression index since `seed` changes every page load, so nothing to
precompute against. Real fix is architectural: bucket-based shuffle
(assign each card a stable small-int bucket, shuffle bucket order instead
of every row) or a periodically-materialized order (recompute a shuffled
`sort_key` column on a cron instead of per-request). Needs its own short
design pass before implementing.

## Wide-tile masonry spans, blocked on real placement-time signal

Reverted (see `TRICKS.md`) because a blind per-id hash can't know whether
spanning will leave a gap — that needs the layout engine's actual column
state at insert time. Revisit once there's a recommendation match score to
use as the "is this card worth spanning" signal, computed alongside real
placement-time state instead of a static hash.
