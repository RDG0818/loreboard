# Future improvements

Deferred upgrade paths — simple version shipped now, here's the next lever
if it stops being enough. Not urgent, not scoped, just don't want to
forget the idea. Newest first.

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
