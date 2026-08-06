# MTG card discovery app — design spec

Date: 2026-08-06
Status: approved, pending implementation plan

## Context

Loreboard's fantasy-art scraping pipeline (Reddit → dropped for onboarding friction; DeviantArt/ArtStation → both built and working, see `2026-08-05-data-pipeline-design.md`) produced a working dataset, but the underlying product idea — a gallery of scraped art you could just as easily browse on the source sites — wasn't solving a real problem. A closer look at ArtStation/DeviantArt/Reddit also showed these sources are fundamentally hostile to programmatic access: Cloudflare-gated detail endpoints, undocumented rate limits, resolution-protected assets, OAuth flows that shift under new accounts (Reddit's Devvit redirect).

Magic: The Gathering via the Scryfall API is a better foundation on every axis that mattered: free, fully documented, no auth for reads, a daily bulk-data export of the entire card database, generous/absent rate limits on image assets, and — critically — a real product gap. Existing MTG tools split into two camps: competitive/synergy tools (EDHRec, Moxfield) and one small unofficial swipe-app (SpellSwipe, low adoption) with no recommendation system built on actual user behavior and no natural-language search. This pivot **fully replaces** the fantasy-art project — the art pipeline, CLIP classification, and the art→music cross-modal matching feature (ChromaDB/`audio.py`/`music.html`) are all removed as part of this work, not left running alongside it.

This is a new sub-project in the same portfolio-piece refactor (ML/AI engineering roles, primary goal). It supersedes the fantasy-art data pipeline and the not-yet-started "backend/frontend read from Postgres/R2" sub-project referenced in the prior spec — those are moot once the art dataset itself is retired.

## Goals

- Bulk-ingest Scryfall's card database (unique artwork, one entry per distinct piece of art) into our own Postgres+pgvector store, refreshed on a schedule.
- A masonry-style, infinite-scroll browsing feed (evolving the existing `src/main.js` pattern) — browsable **without login**, per Scryfall's Fan Content Policy (data/browsing access must remain available anonymously or via free accounts).
- Real user accounts via OAuth (Google), required only for saving cards and viewing recommendations — not for browsing.
- A content-based recommendation system: card text embeddings (reusing the pipeline's existing `embed.py`/Gemini text-embedding-004) computed once at ingest; a user's taste vector computed on demand as the average of their saved cards' embeddings; recommendations via pgvector nearest-neighbor search. No collaborative filtering in this phase — logged as a deliberate future extension.
- Natural-language search: an LLM translates free text ("low cost commanders that do X and Y") into Scryfall's own structured query syntax, run against our local DB.
- View events logged (user_id, card_id, timestamp) from day one, unused by the recommender until a later collaborative-filtering phase — avoids a data-migration gap later.
- Comply with Scryfall's Fan Content Policy: no paywalling data, visible artist attribution wherever art is shown, no implied endorsement, no image manipulation.

## Non-goals

- Collaborative filtering (users-who-liked-X-also-liked-Y) — explicitly deferred; `views` table exists now so the data isn't lost, but no collaborative model is built in this phase.
- Native mobile app / App Store presence — web app only for now; kept API-first enough that a native client could be added later without a backend rewrite, but no PWA manifest/service-worker work is in scope either.
- Passive view-based signal in the recommender — views are logged but the taste vector is saves-only in this phase.
- Any retained fantasy-art functionality — full replacement, not a parallel feature.
- Email/password or magic-link auth — OAuth (Google) only.
- Hybrid structured-filter + embedding rerank for NL search — plain LLM→query-syntax translation only; embeddings aren't used in the search path in this phase (only in the separate recommendations path).

## Architecture

**Backend:** FastAPI, evolving `backend/main.py`. Postgres+pgvector (reusing `db.py`'s connection/schema patterns from the pipeline sub-project). No object storage (R2) — card images are hotlinked directly from `cards.scryfall.io`, which Scryfall's docs confirm has no rate limit, unlike the API host itself.

**Ingestion:** A scheduled job (same GitHub Actions cron pattern as the existing pipeline) downloads Scryfall's daily "Unique Artwork" bulk JSON export, upserts into a `cards` table keyed on Scryfall's card ID, then runs the embed step for any card missing an embedding (`embed.py`, unchanged, reused as-is — no image captioning needed since Scryfall already provides structured oracle text/type/mana cost/colors). Idempotent upsert: re-running is a no-op for unchanged cards, same shape as the existing dedupe-by-hash pattern.

**Auth:** OAuth (Google) via Authlib, session as an httpOnly cookie. No password storage or handling anywhere in the app.

## Data model

New tables (Postgres):

- **`cards`** — Scryfall ID (PK), name, oracle_text, type_line, mana_cost, cmc, colors, color_identity, legalities, artist, image_uris (jsonb), embedding (pgvector column), scryfall_updated_at.
- **`users`** — id (PK), google_sub (OAuth subject ID, unique), email, created_at.
- **`saves`** — user_id + card_id (composite PK), saved_at.
- **`views`** — user_id, card_id, viewed_at. Logged now, not read by any query in this phase.

## API

- `GET /api/v1/cards?cursor=` — paginated card feed for the masonry view. **No auth required.**
- `GET /api/v1/cards/search?q=` — structured search using Scryfall's own query grammar, run against our DB. No auth required.
- `POST /api/v1/search/natural` — free text in; LLM translates to the structured query syntax above, then executes it the same way as `/cards/search`. No auth required (search is browsing, not a personalization feature).
- `POST /api/v1/saves`, `DELETE /api/v1/saves/{card_id}` — requires auth.
- `GET /api/v1/recommendations` — requires auth. Computes the user's taste vector on the fly (average embedding of saved cards) and runs a pgvector nearest-neighbor query.
- `POST /api/v1/views` — requires auth, batched/fire-and-forget logging.
- `GET /auth/login/google`, `GET /auth/callback` — OAuth flow, issues the session cookie.

## Frontend

Evolves `src/main.js` rather than a rewrite — same masonry-layout + `IntersectionObserver` infinite-scroll and click-to-modal pattern already in the codebase, adapted to:

- **Grid shows the `art_crop` image variant, not the full card.** This keeps the browsing feed closer to the original fantasy-art aesthetic this codebase started with, and differentiates from SpellSwipe (which swipes full card images). The full card image, oracle text, and mana cost appear in the click-through modal, where there's room for them. Flagging this as a judgment call, not something explicitly asked for — worth confirming.
- Cursor-paginated fetch from `/api/v1/cards`, replacing the current "fetch all image URLs up front, slice client-side" approach (doesn't scale to the full card corpus).
- Save button calls `/api/v1/saves`; if the user isn't logged in, clicking Save triggers the Google OAuth flow first, then completes the save. Browsing itself never prompts for login.
- Card modal shows name, mana cost, oracle text, and artist attribution (Fan Content Policy requirement), plus a "more like this" strip using the same embedding space as recommendations.
- Search bar wired to `/api/v1/search/natural`.
- A "For You" view hitting `/api/v1/recommendations`, only shown when logged in.

Same Vite + vanilla JS build, no new framework.

## Error handling

- Ingestion: per-card upsert isolation (one malformed record from the bulk dump doesn't kill the run), same pattern as the existing pipeline's per-candidate isolation.
- Embedding backfill: existing `RateLimiter`/`DailyQuota`/`with_backoff` from `embed.py` apply unchanged. A full ~37k-card backfill may span multiple days under the free-tier daily quota; already-embedded cards are skipped on re-run, so this degrades gracefully rather than blocking.
- NL search: if the LLM produces invalid Scryfall query syntax, fall back to a plain full-text search on the raw input rather than erroring the request.
- Recommendations: a user with zero saves gets an explicit "save some cards to get recommendations" response, not a crash — the empty-average case is guarded explicitly.
- OAuth failures: standard Authlib error redirect to a login-failed state; no custom token/session handling to get wrong.

## Compliance (Scryfall Fan Content Policy)

- Browsing and search work without login — data access is never paywalled.
- Artist name shown wherever card art is displayed (grid overlay and modal).
- No cropping/blurring/watermarking of card images.
- No use of Scryfall branding in a way implying endorsement.
- The app adds real value beyond raw data access (recommendations, NL search, personalized saves) — not a bare repackaging of Scryfall's data.

## Testing

Same per-module pytest convention as the existing pipeline. New coverage: ingestion upsert/dedupe logic, NL-search query-syntax-fallback path, recommendation taste-vector math (including the zero-saves edge case), and auth-required-vs-anonymous route gating. No new frontend test suite — matches current project convention; frontend verification is manual smoke-testing via the `run` skill once built.

## What gets removed

- `backend/pipeline/scrape_deviantart.py`, `scrape_artstation.py`, `classify_clip.py`, `classify_heuristics.py`, `caption.py`, `caption_gemini.py`, `dedupe.py`, `persist.py`, `storage.py`, and their tests — image-scraping/classification/captioning is entirely inapplicable to structured card data.
- `backend/pipeline/run.py` — rewritten as the Scryfall ingestion entrypoint, not an evolution of the scrape→classify→caption→embed→persist loop.
- `backend/audio.py`, `backend/vectordb.py`, `backend/chroma_db/`, `music.html`, `src/music.js` — no MTG equivalent to art→music matching.
- `backend/image_sorter/` — already mostly dead, fully removed now.
- `backend/database.py`'s SQLite schema — replaced by the Postgres schema above.

## Reused unchanged

- `backend/pipeline/embed.py`, `backend/pipeline/rate_limit.py`, `backend/pipeline/db.py`'s connection-and-extension-bootstrap pattern, `backend/pipeline/config.py`'s shape, the GitHub Actions scheduled-workflow pattern, and the `src/main.js` masonry/infinite-scroll/modal frontend pattern.

## Open items for a later sub-project

- Collaborative filtering, once real usage data exists (the `views` table is the seed for this).
- Native/PWA mobile client.
- Passive view-weighted signal in the recommender.
