# Polish backlog

Raw capture point for fixes/ideas as they're spotted. Not prioritized, not
grouped — just dump here. Triage periodically into sweeps below.

## Inbox

(add items here — one line each, area tag prefix: `[fe]` frontend, `[be]` backend, `[data]` pipeline/data, `[ge]` general)

(empty — everything triaged into sweeps/later below as of this pass)

## Done

- [be] "green commander" search only returned 20-30 results instead of hundreds — root cause: `cards.search_cards()` hardcoded `limit=60`, NL translation itself was correct (`c:G t:legendary t:creature`, true match count 1805). Fixed: limit 60→300, plus `main.js` search-results loop was `await`-ing each card's image sequentially before the next (bad UX on top of the cap) — now loads all images in parallel via one `imagesLoaded(gallery)` call. Not yet committed.
- [fe] framework switch decision — discussed in detail (sidebar/masonry aren't "drop-in" in any framework; RN doesn't share UI code with web React either — different render target entirely). Decided: staying vanilla JS.
- [fe] frontend cleanup sweep — extracted `src/cardRender.js` (`cardArtUrl`, `createCardWrapper`) and wired it into `main.js`/`favorites.js`/`recommendations.js`, replacing 3 copies of the same DOM-building block. Removed ~170 lines of dead CSS from the deleted music/audio feature (`.stats-layout`, `.chart-section`, `.bubble-legend`, `canvas`, `.music-page`, `.image-selector`, `.btn`, `.song-list`/`.song-item`, `.image-preview`/`.image-display`, `.preview-panel`, `.tag-display`/`.tag-pill`, `.image-title`) — grepped for orphan class refs first, none found. `.save-btn`/`.pulse` CSS kept (unused but earmarked for the styling-direction sweep). Verified via `vite build`. Not yet committed.
- [fe] card-click modal flash (art-crop → full card) — root cause: `main.js`'s click handler set `modalImg.src` to the grid thumbnail then re-fetched `/api/v1/cards/{id}` and swapped to the full image once it resolved; the two images have different aspect ratios so the async swap read as a jump. The fetch was leftover from before the modal got trimmed to art+artist+save — `cards.py`'s list/search responses already carry full `image_uris` and `artist`. Fixed by keeping a `cardsById` map as cards render and reading from it synchronously on click. First fix pass swapped straight to the (uncached) full image and introduced a second bug — the *previous* card's image stayed on screen for a beat before the new one loaded, since `<img>` doesn't clear its bitmap on `.src` reassignment. Second fix: show the grid thumbnail (already cached, always correct) immediately, preload the full image in the background, swap only on load, guarded by `currentModalCardId` so a fast second click can't let a stale preload land on the wrong card. `vite build` clean both passes. Not yet committed.
- [fe] frontend interaction bugs sweep — 3 fixes: (1) infinite scroll missing loads on fast scroll: `IntersectionObserver` samples geometry at throttled checkpoints, so a fast/flung scroll could move `#scroll-trigger` from below-viewport to already-passed between samples without ever reporting `isIntersecting: true`, silently dropping the load; added a `scroll`/`resize` fallback check in `main.js` (`loadMoreCards`'s own guards make redundant calls safe). (2) sign-in only surfaced via 401 redirect: added `GET /api/v1/me` (`backend/auth.py`, tested) returning `{logged_in, email}` instead of 401'ing, plus a `#sidebar-signin` link (hidden unless logged out) wired via new `src/authStatus.js` on all 3 pages. (3) reported mid-sweep: collapsing the sidebar squished/off-centered the masonry grid — root cause: Masonry.js only re-lays-out on `window` resize events by default, and the sidebar collapse is a CSS width *transition*, not a window resize, so Masonry never noticed the container got wider and kept stale cached item positions; fixed via `sidebar.js` dispatching a `sidebar:layout-change` event on the sidebar's `transitionend`, which `main.js`/`favorites.js`/`recommendations.js` all listen for to call `msnry.layout()`. `vite build` clean, `pytest backend/` 75 passed. Not yet committed.
- [fe] frontend styling direction & visual identity sweep — direction picked via 3 interactive mockups in an artifact (minimal/clean, Pinterest-close, moody premium/dark): landed on Pinterest-close layout (pill buttons/shadows) with the sidebar recolored to blend into the page bg instead of a separate charcoal block, and accent swapped from red to mythic-rare orange (`#e2711d`). Implemented: sidebar now `#000` + hairline border, collapsible via new `.sidebar-toggle` chevron + `src/sidebar.js` (persists to localStorage) on all 3 pages; search bar restyled as a dark pill with orange focus ring; "Browse Cards" header removed from `index.html` (unused Uncial Antiqua font link dropped too); card-detail modal trimmed to art + artist + Save only (`.modal-card` column layout, `main.js` no longer fetches/renders name/mana-cost/type-line/oracle-text); hover save button wired into `cardRender.js` (`createSaveToggler` + `createCardWrapper`'s optional save-btn) live on browse grid, search results, and recommendations, with the modal's save button now sharing the same toggle function and syncing the grid card's button state. Verified via `vite build` + dev-server asset checks (no browser-automation tool available in this env, so no live visual/interaction pass). Not yet committed.

- [fe] bad art_crop on Summon: Choco/Mog (both printings) — Scryfall's own `art_crop` bounding box for this card bakes in a sliver of rules text (top) and the type-line bar (bottom); confirmed not our CSS/pipeline (other Saga-layout cards checked clean, `object-fit`/height not set anywhere prior to this). Added a small per-card-id override map in `cardRender.js` (`ART_CROP_OVERRIDES`) — on image load, computes a cropped `aspect-ratio` + `object-fit: cover` + `object-position` from top/bottom fractions (measured via PIL against the downloaded jpegs) to trim the bars without a server-side reprocessing pipeline. Applies wherever `createCardWrapper` is used (grid, search, recommendations). `vite build` clean.

- [be] feed order randomization — `fetch_cards_page` (`backend/pipeline/cards.py`) now takes an optional `seed`; when given, orders by `md5(id || seed)` tie-broken by `id` instead of plain `id`, still keyset-paginated (no offset, no dupes/gaps across pages — verified against real DB with a fixed seed: zero overlap between pages, deterministic per seed, differs across seeds). Cursor format unchanged (`cursor` is still just the last card's `id`) — backend recomputes the hash for that id using the seed sent alongside it, so no API contract or frontend cursor-tracking change needed. `src/main.js` generates one `feedSeed` per page load (module scope), sent with every `/api/v1/cards` request; stable through infinite scroll and clearing search, fresh shuffle on reload. Left as the extension point for the recommendation system: swapping `md5(id || seed)` for a per-user recommendation score (or blending both) only touches the two ORDER BY/WHERE expressions in `fetch_cards_page` — pagination shape and API contract don't move. Without a seed, behavior/SQL is byte-for-byte the original `ORDER BY id` (existing callers unaffected). Known tradeoff: no supporting index on the hash expression, ~90ms/page seq scan at current 54k-row table size — flagged under the backend search quality sweep below rather than solved here (small enough to leave, same class of problem as the `ILIKE` index gap). `pytest backend/` 78 passed, `vite build` clean.

- [ge] "off-vibe" card filter (memes/playtest/crossover alt arts), default on — settled via a few grounded questions: Scryfall's own `set_type == 'funny'` covers both silver-border Un-sets and official Mystery Booster Playtest cards in one field; `promo_types` containing `universesbeyond` covers all crossover sets (Marvel, Final Fantasy, LOTR, Doctor Who, etc — confirmed this includes the Choco/Mog card from the earlier crop fix, hidden by default now, visible again with the toggle on). Added `set_type TEXT` and `is_universes_beyond BOOLEAN NOT NULL DEFAULT FALSE` columns (`backend/pipeline/db.py`, `CREATE TABLE`+`ALTER TABLE ADD COLUMN IF NOT EXISTS` since this project has no migration tool and the table already had 54k rows), derived at ingest time in `card_row_from_json`. `fetch_cards_page` takes `include_all: bool = False`; when off, adds `set_type IS DISTINCT FROM 'funny' AND NOT is_universes_beyond` to the WHERE clause (combines cleanly with the seeded-order cursor logic from the previous item — same keyset pagination, filter is just another ANDed predicate). `/api/v1/cards` exposes it as `show_all`. Frontend: eye/eye-off toggle button in the sidebar (`index.html`/`main.js`, `#show-all-toggle`), state in localStorage, defaults to filtered; clicking it resets and reloads the browse feed (factored the reset-and-reload steps that used to live only in the "clear search" path into a shared `resetAndReloadFeed()`, now used by both). Scoped to the browse feed only — search stays intent-driven (search "Spider-Man", get the Spider-Man card even filtered) and isn't touched by this flag; favorites/recommendations unaffected too (out of scope, can extend later if wanted). Ran the schema migration and a full reingest against the live DB to backfill the new columns on existing rows (54122 cards updated, no Gemini calls — just re-pulled Scryfall bulk JSON) — verified counts (1020 funny, 7119 Universes Beyond, 45984 remain after filtering out of 54122) and confirmed Choco/Mog is now correctly flagged and filtered. `pytest backend/` 83 passed, `vite build` clean.

- [fe] masonry wide-tile spans — Pinterest-style width variation to break up grid uniformity. `isWideCard(cardId)` in `cardRender.js`: a card is wide if a cheap hash of its id lands on 0 mod 8 (~1-in-8, verified against 100k random ids: 12.4% vs. 12.5% target) — deterministic per id, so the same card is always/never wide across refetches (no layout flicker), and reuses the same hash-based-determinism pattern as the feed seed. `createCardWrapper` only applies it when a caller opts in via `enableWideTiles`; `main.js` gates that behind a single `ENABLE_WIDE_TILES` constant (flip to `false` to fully disable — nothing else to touch) and guards the very first card in the gallery to never be wide, checked against the live DOM rather than `cardsById` (which — being reset-agnostic, used for modal lookups — would've stayed non-empty across a feed reset and broken the guard). The guard matters because Masonry's `columnWidth: '.image-wrapper'` config reads the *first* matched element's width to set its column unit; a wide first card would throw off every column-count calc after it. `.image-wrapper.wide` in `style.css` is `2 * column + 1 * gutter` width, image itself unconstrained (`height: auto`) so no distortion, just bigger. Scoped to the main browse feed only, not search results or other pages. Extension point for later: swap the hash in `isWideCard` for "this card scores well against your recommendations" once that scoring exists — noted in `main.js`/`cardRender.js` comments, mentioned by the user as the likely next step. `vite build` clean, `pytest backend/` 83 passed (backend untouched by this item).

- [fe] wide-tile spans left gaps in the masonry grid — root cause: Masonry.js does greedy column-height tracking, not real bin-packing. A 2-column-wide item snaps both columns to the taller one's height, and whatever gap already existed in the shorter column never gets backfilled (layout processes items in DOM order, no lookback). Verified before swapping: `masonry-layout` and `packery` (same author, desandro) both build on the shared `outlayer` base (`var Packery = Outlayer.create('packery')`) — confirmed `itemSelector`/`columnWidth`/`gutter`/`percentPosition` options and `.appended()`/`.layout()`/`.remove()` instance methods all present in Packery's source before touching code, since Packery's whole pitch ("gapless, draggable grid layouts", true bin-packing) is exactly the fix needed here. Swapped `masonry-layout` → `packery` in `package.json` and all three files (`main.js`, `favorites.js`, `recommendations.js`) — identifier and constructor rename only (`Masonry` → `Packery`), no config or call-site changes since the API surface is identical. `vite build` clean, `pytest backend/` 83 passed (backend untouched). No live browser pass possible in this environment (no Playwright/chromium-cli available) — verified via source-level confirmation of the shared API and a clean build/typecheck only; worth a manual look in a real browser to confirm the gaps are actually gone.

- [fe] wide-tile spans still gapped after the Packery swap — user confirmed live in browser. Root cause: Packery's bin-packer only sees geometry, not our intent; a 2-col item still forces the shorter column to jump to match, same visual gap, just moved/reshaped rather than eliminated — placement-time knowledge of "will this leave a gap" isn't something we can bolt on from outside the layout engine. Reverted: `ENABLE_WIDE_TILES` flipped back to `false` in `main.js` (the toggle from the original implementation made this a one-line change, code otherwise untouched and left in place). Packery swap itself kept — still the right gapless bin-packer for plain single-column masonry regardless of wide tiles. Blocked until the recommendation system exists: the plan is to only mark a card wide when it's both a strong recommendation match *and* the current column state (known at insert time) proves spanning won't leave a gap — needs real placement-time state, not a pure per-id hash. Revisit then.

- [be] `pg_trgm` GIN indexes on `cards.name`/`oracle_text`/`type_line` — fixes the `ILIKE '%word%'` seq scans in `query_parser.py` (leading wildcard, so a plain B-tree index can't help). Added `CREATE EXTENSION IF NOT EXISTS pg_trgm` + 3 GIN indexes to `db.py`'s `SCHEMA_SQL`, ran against the live DB. Verified via `EXPLAIN`: planner switched from sequential scan to bitmap index scan on `cards_name_trgm_idx`. Write-time cost only (index maintained at ingest, no runtime downside). `pytest backend/` 83 passed. See `TRICKS.md` for the informal writeup.

- [be] in-process cache for Gemini NL→query translation (`backend/nl_search.py`) — module-level dict keyed on normalized (trimmed/lowercased) request text; a cache hit skips the Gemini call entirely and goes straight to `parse_query`. Exact-string match only, paraphrases still miss. Resets on process restart, not shared across instances — fine at current scale; upgrade path (DB-backed/shared cache, semantic match via existing `pgvector` embeddings) noted in `FUTURE_IMPROVEMENTS.md`. Two new tests cover cache-hit-skips-model and normalization; `pytest backend/` 85 passed.

## Sweeps

Once the inbox has enough related items, group them into a sweep here.
Each sweep is small enough to run through its own
brainstorm → spec → plan → subagent-driven-development cycle.
Sweeps with no file overlap can run in parallel (`dispatching-parallel-agents`).

### Sweep: frontend cleanup (found during framework review, not from inbox)
Status: done — see Done section above

### Sweep: frontend styling direction & visual identity
Status: done — see Done section above

### Sweep: frontend interaction bugs
Status: done — see Done section above

### Sweep: backend search quality
Status: in progress
Items:
- [be] `ILIKE '%word%'` scans had no supporting index — fixed, see Done section below.
- [be] NL path pays a Gemini round-trip every query (no cache) — fixed, see Done section below.
- [be] `fetch_cards_page`'s `md5(id || seed)` order expression has no index — not a simple index fix (seed differs per page-load, so a normal expression index can't be precomputed against it); needs its own small design pass (bucket-based shuffle or a periodically-materialized order). Not started.
- [be] NL→query-syntax translation just hopes the LLM emits well-formed output, falls back to poor substring search on failure — consider constrained/structured output (function-calling or JSON schema) instead of parsing free text. Not started.
Depends on: none
Parallel-safe with: everything else — backend-only, different files from all `[fe]` sweeps.

### Sweep: feed variety
Status: done — see Done section above
Items:
- [be] card feed order is static (`ORDER BY id`) — randomize — done
- [ge] some cards feel out of place (memes, playtest cards, superhero/crossover alt arts) — add a filter/flag, default off (filtered), user-toggleable — done
- [ge] masonry looks better with size variation; most crops are currently uniform — add some randomized/varied sizing to break up the grid — done
Depends on: none. Small cross-cutting sweep (backend: ordering/flag column; frontend: masonry sizing) — worth doing as one sweep since it's small, not two.
Parallel-safe with: backend search-quality sweep and all frontend sweeps (touches `fetch_cards_page`/`cards` schema + masonry CSS/JS, disjoint from the others).

### Sweep: codebase cleanup (found during architecture review, not from inbox)
Status: not started — brainstormed 2026-08-07, design approved, plan not yet written
Motivation: general reorg/dedup/comment-cleanup pass ahead of a system
design diagram the user plans to do once this settles — the goal is a
directory layout and module boundaries clean enough to map straight onto
that diagram.
Items:
- [be] `backend/pipeline/` currently mixes two unrelated things: a DB-access
  layer (`db.py`, `cards.py`, `interactions.py`, `users.py` — used by both
  the live API and the ingest script) and an ingest-only pipeline
  (`run.py`, `embed.py`, `config.py`, `rate_limit.py`, `gemini_retry.py` —
  only ever invoked by the nightly cron). Split into `backend/db/`
  (rename `pipeline/db.py` → `db/connection.py`, move `cards.py`/
  `interactions.py`/`users.py` in unchanged) and `backend/ingest/` (the
  5 pipeline-only files, unchanged). Touches ~20 files' imports, every
  test file, and `.github/workflows/data_pipeline.yml`
  (`python -m backend.pipeline.run` → `backend.ingest.run`). Do this move
  first, as its own checkpoint (grep for stale `backend.pipeline`
  references + full `pytest` pass), before any of the items below.
- [be] Split `backend/auth.py` into `backend/routers/auth_router.py`
  (login/callback/me endpoints) and `backend/services/auth.py`
  (`get_current_user`/`require_user`). Move `nl_search.py`,
  `query_parser.py`, `recommendations.py` into `backend/services/`. Move
  the 5 `*_router.py` files into `backend/routers/`. Not started.
- [be] `conn = get_connection(); try: ...; finally: conn.close()` is
  duplicated identically in 8 places across the routers + `auth.py`.
  Replace with a FastAPI `Depends`-generator (`backend/db/connection.py::
  get_db()`, yield conn / close on request end) — pure dedup, same
  one-connection-per-request behavior, no perf change. Do this after the
  directory move lands, not combined with it. Not started.
- [fe] Three duplicated patterns across `main.js`/`favorites.js`/
  `recommendations.js`: fetch-savedCardIds-into-a-Set boilerplate (main.js,
  recommendations.js), Packery init options object (main.js x2,
  recommendations.js), and the 401→redirect-to-login check (favorites.js,
  recommendations.js, `createSaveToggler` in `cardRender.js`). Extract into
  a new `src/api.js` (`apiFetch`, `fetchSavedCardIds`, `createMasonry`) —
  no directory restructuring, just 3 new small functions. `cardRender.js`/
  `sidebar.js`/`authStatus.js` already single-purpose, not touched. Not
  started.
- [ge] Docs pass once the backend move lands: fix any stale `pipeline`
  references in `README.md`/comments/docstrings. Flag (don't fix) any
  other placeholder-feeling infra choices spotted along the way (e.g.
  `SESSION_SECRET_KEY`/`FRONTEND_ORIGIN` env defaults, connection-per-
  request instead of pooling) into `FUTURE_IMPROVEMENTS.md` — the
  Supabase/Vercel replatform intent is already logged there. Not started.
- Explicitly out of scope for this sweep: DB connection pooling (behavior
  change, deferred), Supabase/Vercel migration (deferred, logged in
  `FUTURE_IMPROVEMENTS.md`), touching the flagged-off wide-tile code in
  `cardRender.js` (deliberately deferred, see that file's Done entry above
  and `FUTURE_IMPROVEMENTS.md`).
Depends on: none.
Parallel-safe with: nothing else queued right now — this sweep touches
nearly every backend file's import lines, so land it before starting any
other backend sweep (e.g. the still-open NL structured-output item in
"backend search quality" above) to avoid merge pain.

## Later (real scope, not "polish" — separate future specs, not sweeps yet)

- `[ge]` multiple boards, Pinterest-style (own board per theme/deck) — new feature
- `[ge]` show card flavor text instead of raw oracle-text/type-line syntax in places — content/design call
- `[ge]` explore more agentic-orchestration patterns — resume/tech-exploration, orthogonal to product work
- `[ge]` once project is past beta: replace this backlog doc with Jira + Claude MCP integration
