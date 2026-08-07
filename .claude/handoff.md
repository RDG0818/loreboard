# Handoff

## Goal

Sweep-based polish/cleanup pass on a vanilla-JS MTG Pinterest-style card
discovery app (FastAPI + psycopg2 backend, Postgres+pgvector, Scryfall
bulk-data ingest). Work is tracked in `docs/notes/polish-backlog.md` — a
raw inbox → grouped sweeps → done log, no external ticket tracker.

This session ran a **codebase-cleanup sweep** (reorg/dedup, not new
features) requested by the user ahead of them drawing a system-design
diagram once the codebase settles: split the flat `backend/` and
`backend/pipeline/` packages into clean layers (`db/`, `ingest/`,
`routers/`, `services/`), deduped repeated DB-connection boilerplate via
FastAPI `Depends`, and deduped repeated frontend fetch/masonry/save-toggle
logic into `src/api.js`. Zero intended behavior change — pure structure.

The **backend-search-quality sweep** from the previous session (seed-shuffle
index redesign, NL structured-output parsing) is still open and untouched
this session — see Next steps.

## Current state

All work is committed. The feature branch (`worktree-codebase-cleanup`,
built in a git worktree at `.claude/worktrees/codebase-cleanup/`) was
**merged into local `main` by the user, outside this session** (this
session's git tooling is sandboxed to the worktree and cannot touch the
main checkout). **Push-to-origin status is unverified** — the user merged
locally; confirm `git status`/`git log origin/main..main` on `main` before
assuming this is on the remote.

New backend layout (all under `backend/`):
- `db/` — `connection.py` (was `pipeline/db.py`; has `get_connection()`,
  `init_schema()`, `SCHEMA_SQL`, and new `get_db()` — a FastAPI generator
  dependency), `cards.py`, `interactions.py`, `users.py` (all moved
  unchanged from `pipeline/`)
- `ingest/` — `run.py`, `embed.py`, `config.py`, `rate_limit.py`,
  `gemini_retry.py` (moved unchanged from `pipeline/`; this is the
  Scryfall bulk-ingest cron job, invoked via `python -m backend.ingest.run`
  — `.github/workflows/data_pipeline.yml` updated to match)
- `routers/` — `cards_router.py`, `recommendations_router.py`,
  `saves_router.py`, `search_router.py`, `views_router.py` (moved,
  refactored to `conn=Depends(get_db)`), plus new `auth_router.py` (split
  out of old flat `auth.py`: `login_google`/`auth_callback`/`me`)
- `services/` — `nl_search.py`, `query_parser.py`, `recommendations.py`
  (moved unchanged), plus new `auth.py` (split out of old flat `auth.py`:
  `get_current_user`/`require_user`)
- `backend/pipeline/` and the old flat router/auth files no longer exist.
- Tests mirror the new layout: `backend/{db,ingest,routers,services}/tests/`,
  plus a new `backend/tests/test_main.py` (smoke test asserting all 12
  route paths are registered in `backend/main.py` — added because nothing
  previously imported `backend.main`, so a broken `include_router` call
  would have gone uncaught).

Frontend: new `src/api.js` exports `apiFetch(apiBase, path, options)`
(centralizes 401→redirect-to-login), `fetchSavedCardIds(apiBase)`, and
`createMasonry(gallery)` (the common Packery config). Wired into
`main.js`, `recommendations.js` (all three helpers), `favorites.js`
(`apiFetch` only — its Packery config genuinely differs, kept inline), and
`cardRender.js`'s `createSaveToggler` (`apiFetch` only).

Verified: `pytest backend/ -q` → **86 passed** (85 + the new
`test_main.py` smoke test). `npx vite build` → clean, **39 modules** (38 +
new `api.js`).

**Deliberately out of scope / left alone this sweep** (see
`FUTURE_IMPROVEMENTS.md` and Known issues below for the reasoning on
each): DB connection pooling, Supabase/Vercel migration, the flagged-off
wide-tile code in `cardRender.js` (`isWideCard`/`ART_CROP_OVERRIDES`/
`ENABLE_WIDE_TILES`), `auth_router.auth_callback` and `services/auth.py`'s
`get_current_user` still hand-roll `get_connection()`/try-finally instead
of `Depends(get_db)`.

## Files in flight

Everything below is committed (8 commits, `335d8601..db6dc85` on the
now-merged branch). Nothing uncommitted.

- `FUTURE_IMPROVEMENTS.md` — added a "Replatform: Supabase / Vercel"
  section logging that intent for later; updated the `nl_search.py` path
  reference to `backend/services/nl_search.py`
- `docs/notes/polish-backlog.md` — added the "codebase cleanup" sweep
  (now marked done, with a closing summary)
- `docs/superpowers/plans/2026-08-07-codebase-cleanup-implementation.md` —
  new, the full 6-task implementation plan this session executed
- `backend/pipeline/{db,cards,interactions,users}.py` → moved to
  `backend/db/{connection,cards,interactions,users}.py`
- `backend/pipeline/{run,embed,config,rate_limit,gemini_retry}.py` →
  moved to `backend/ingest/{...}.py`; `backend/pipeline/` deleted
- `.github/workflows/data_pipeline.yml` — `backend.pipeline.run` →
  `backend.ingest.run`
- `backend/{cards,recommendations,saves,search,views}_router.py` → moved
  to `backend/routers/{...}.py`, refactored to use `Depends(get_db)`
- `backend/auth.py` → split into `backend/routers/auth_router.py` +
  `backend/services/auth.py`
- `backend/{nl_search,query_parser,recommendations}.py` → moved to
  `backend/services/{...}.py`
- `backend/db/connection.py` — added `get_db()` generator dependency
- `backend/tests/` (old flat dir) → deleted, tests redistributed into
  `backend/{db,ingest,routers,services}/tests/`; new
  `backend/tests/test_main.py` + `backend/tests/__init__.py` added fresh
  (smoke test, see Current state)
- `src/api.js` — new file (`apiFetch`, `fetchSavedCardIds`, `createMasonry`)
- `src/main.js`, `src/recommendations.js` — wired to all 3 `api.js` helpers
- `src/favorites.js`, `src/cardRender.js` — wired to `apiFetch` only
- `backend/ingest/embed.py` — fixed a stale comment (`db.py` →
  `backend/db/connection.py`)

## What changed

No uncommitted diff — everything above is committed. Full history:
`git log 335d8601..db6dc85` (8 commits) on `main` (post-merge).

## Failed attempts

- No failed/reverted approaches this session — the entire sweep was a
  planned mechanical refactor (file moves + import fixes + two dedup
  passes), executed via `subagent-driven-development` with a task review
  after each of 6 tasks and a final whole-branch review, all of which came
  back clean or with only minor/deferred findings (see Known issues).
- One plan gap was caught and self-corrected during execution, not a
  failure: Task 3's brief (written by the controller) omitted that
  `cards_router.py` also imports from `query_parser` — the implementer
  subagent found and fixed it using the same import-rewrite pattern used
  everywhere else in that task. Verified correct by task review.

## Known issues / blockers

- **Push-to-origin status unverified.** The merge into local `main`
  happened outside this session (git-sandboxed to the worktree). Check
  `git log origin/main..main` and push if needed before treating this
  work as landed remotely.
- **Worktree cleanup status unknown.** The user was given
  `git worktree remove .claude/worktrees/codebase-cleanup` +
  `git branch -d worktree-codebase-cleanup` to run after merging, but
  whether they ran it wasn't confirmed. Check `git worktree list` /
  `git branch` before assuming it's cleaned up. (This handoff file itself
  was written to the worktree's own `.claude/handoff.md` — this session's
  git sandboxing blocked writing directly to the main checkout's
  `.claude/handoff.md`. Whoever resumes should copy/merge this file's
  content into `/home/ryan/Repos/loreboard/.claude/handoff.md` if the
  worktree gets removed.)
- **Accepted tradeoff, not a bug:** switching to `Depends(get_db)` means
  `Depends()` params resolve *before* the handler body runs, so
  `cards_router.search_cards` (bad-query 400 path) and
  `search_router.natural_search` (bad-body 422 path) now open+close a DB
  connection on requests that previously opened zero (validation used to
  run before `get_connection()`). Final review confirmed this is real,
  bounded to those paths (unauthenticated requests via `require_user`
  still open zero connections — that check still runs first), and does
  not leak connections on any error path. User explicitly chose to accept
  it in favor of uniform `Depends(get_db)` across all 10 endpoints rather
  than special-casing 2 of them.
- **Two DB-connection-management styles now coexist** (final-review
  observation, not fixed this sweep): `auth_router.auth_callback` and
  `services/auth.py`'s `get_current_user` still hand-roll
  `get_connection()`/try-finally, because `get_current_user` is called
  both as a route dependency (via `require_user`) and directly (from
  `me()`), so folding it into `Depends(get_db)` isn't a pure dedup the way
  it was for the other 10 endpoints. `auth_callback` itself *could* safely
  take `Depends(get_db)` — final review flagged this as worth deciding
  before the system diagram gets drawn, since "how does a request get a
  DB connection" currently has two answers. Not urgent, not done.
- **`src/api.js` naming is slightly impure** (final-review observation,
  left alone deliberately): it bundles two HTTP helpers with
  `createMasonry` (a Packery/layout factory), so `cardRender.js` now
  transitively imports `Packery` just for `apiFetch`. No functional
  impact (every page already loaded Packery). Reviewer suggested
  `src/masonry.js` or `src/shared.js` as an eventual rename; not done,
  flagging for the diagram pass.
- Everything else from the previous handoff still applies and wasn't
  touched this session: `fetch_cards_page`'s `md5(id || seed)` order
  expression still has no supporting index (needs a bucket-based-shuffle
  or materialized-sort-key design decision, see
  `FUTURE_IMPROVEMENTS.md`); NL→query structured-output parsing still not
  started; still no live-browser verification tooling in this environment
  (no playwright/chromium) — frontend changes need a manual eyeball check,
  though this session's frontend changes are refactor-only (no DOM/CSS/
  behavior change), so risk is low.

## Next steps

1. **Verify the merge landed as expected**: confirm `main` has the 8
   cleanup commits, decide whether to `git push origin main`, and clean up
   the worktree (`git worktree remove .claude/worktrees/codebase-cleanup`
   + `git branch -d worktree-codebase-cleanup`) if not already done. This
   is the first thing to check before anything else.
2. User mentioned wanting to do a **system-design visualization** once
   "the dust has settled" on this cleanup — the new `db/ingest/routers/
   services` layering was specifically designed to map cleanly onto that.
   Worth checking in on whether that's next, and if so, deciding on the
   two open layering-purity questions first (`auth_callback`'s
   `Depends(get_db)` holdout, `src/api.js`'s naming) so the diagram
   doesn't need a redo.
3. Resume the still-open **backend-search-quality sweep**: design +
   implement the seed-shuffle index fix (bucket-based shuffle vs.
   materialized sort-key — pick via short discussion with the user first),
   then structured-output NL→query parsing, then mark that sweep done in
   `docs/notes/polish-backlog.md`.
4. No other sweep is queued after that — check the "Later" section at the
   bottom of `docs/notes/polish-backlog.md` for bigger, not-yet-scoped
   features (multi-board support, flavor-text display, etc.) if the user
   wants to move past polish sweeps entirely.

Workflow notes for whoever picks this up: user asks "commit and push" (or
equivalent) explicitly each time — never commit/push proactively; this
session additionally would not merge worktree branches into main directly
(harness-blocked) and required the user to do that step themselves outside
the session. For exploratory "what's your idea?" questions, give a short
(2-3 sentence) recommendation + tradeoff and wait for redirect before
implementing. Keep `TRICKS.md` and `FUTURE_IMPROVEMENTS.md` updated
whenever a technique or a deliberately-deferred upgrade comes up — user
explicitly asked for these as running logs. This session used
`subagent-driven-development` (fresh implementer subagent per task + task
review + final whole-branch review) for the first time on this project —
worked well for a mechanical multi-file refactor; worth reusing for
similarly-shaped work (the seed-shuffle/NL-parsing sweep is more
design-heavy and probably doesn't need the same weight).
