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
Status: not started
Items:
- [be] search is slow — investigate: NL path pays a Gemini round-trip every query (no cache), and `search_cards`'s `ILIKE '%word%'` scans have no supporting index (trigram/GIN would help `name`/`oracle_text`, `type_line` filters)
- [be] NL→query-syntax translation just hopes the LLM emits well-formed output, falls back to poor substring search on failure — consider constrained/structured output (function-calling or JSON schema) instead of parsing free text
Depends on: none
Parallel-safe with: everything else — backend-only, different files from all `[fe]` sweeps.

### Sweep: feed variety
Status: not started
Items:
- [be] card feed order is static (`ORDER BY id`) — randomize
- [ge] some cards feel out of place (Secret Lair drops etc.) — add a filter/flag, default off, user-toggleable
- [ge] masonry looks better with size variation; most crops are currently uniform — add some randomized/varied sizing to break up the grid
Depends on: none. Small cross-cutting sweep (backend: ordering/flag column; frontend: masonry sizing) — worth doing as one sweep since it's small, not two.
Parallel-safe with: backend search-quality sweep and all frontend sweeps (touches `fetch_cards_page`/`cards` schema + masonry CSS/JS, disjoint from the others).

## Later (real scope, not "polish" — separate future specs, not sweeps yet)

- `[ge]` multiple boards, Pinterest-style (own board per theme/deck) — new feature
- `[ge]` show card flavor text instead of raw oracle-text/type-line syntax in places — content/design call
- `[ge]` explore more agentic-orchestration patterns — resume/tech-exploration, orthogonal to product work
- `[ge]` once project is past beta: replace this backlog doc with Jira + Claude MCP integration
