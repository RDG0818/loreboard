# Data pipeline rewrite — design spec

Date: 2026-08-05
Status: approved, pending implementation plan

## Context

Loreboard's original image dataset was lost (local folder gone). The existing scraping code (`backend/web_scrapers/reddit_scraper.py`, `backend/web_scrapers/deviantart_scraper.py`) underperformed for content relevance — Reddit lacked volume and had too much off-topic content from a single hardcoded subreddit; DeviantArt's single hardcoded tag search ("magic") wasn't targeted enough. ArtStation, which produced the best manual results previously, is being deliberately excluded — scraping it was impractical last time and it has no clean public API for bulk browsing.

This is the first of several sub-projects in an intensive refactor of Loreboard, targeted as a portfolio piece for ML/AI engineering roles (primary) and as a general fullstack showcase (secondary). Later sub-projects (not covered here): ML/recommendation core, backend API, frontend, deployment/infra.

## Goals

- Rebuild and continuously grow the fantasy-art image dataset from sources with legitimate APIs (Reddit, DeviantArt) — no ArtStation scraping.
- Run automatically on a schedule (both sites publish new art over time), without needing an always-on server.
- Fix the two root causes of poor results: insufficiently targeted sources (Reddit subreddit list, DeviantArt tags) and an unreliable quality/relevance filter (CLIP classifier).
- Land the dataset somewhere durable and queryable by the future backend — not local disk.
- Keep the pipeline resilient to third-party rate limits so a limit on one API doesn't kill the whole run.

## Non-goals

- ArtStation scraping.
- Real-time/event-driven ingestion (Kafka-style) — batch/scheduled is sufficient at this volume.
- Airflow or any persistent-scheduler orchestration — no always-on infra is available; GitHub Actions cron is the scheduler.
- Migrating the existing backend API or frontend (separate sub-project).

## Architecture

**Orchestration:** GitHub Actions scheduled workflow (`cron` trigger), single job per run.

**Storage:**
- **Metadata + vectors:** Hosted Postgres with the `pgvector` extension (Supabase — free tier, native pgvector support, room to add auth later for the frontend sub-project). Replaces the current local SQLite file and separate local ChromaDB.
- **Images/audio files:** Cloudflare R2 (S3-compatible API, free tier, no egress fees). Replaces local `backend/image_dataset` / `backend/audio_dataset` folders.
- **Secrets:** GitHub Actions repo secrets (`REDDIT_*`, `DEVIANTART_*`, `GOOGLE_API_KEY`, `DATABASE_URL`, R2 access keys). `deviantart_token.txt` is removed from git tracking and added to `.gitignore` — it was previously committed to the repo (dead/unused credential, but should not recur).

**Pipeline structure:** One GitHub Actions job runs a Python entrypoint that calls distinct stage modules in sequence. No multi-job/artifact-passing architecture — unjustified complexity at this dataset size (hundreds/thousands of images, not millions), and a single job is easier to debug locally.

## Pipeline stages

1. **`scrape`** — Pulls candidate images with source metadata (url, title, source) from:
   - Reddit (PRAW), with a broadened, configurable subreddit list (not just `ImaginaryBestOf`).
   - DeviantArt, with better-targeted tags/queries (not just a single hardcoded "magic" search).
   Writes raw images to a local tmp dir in the runner.

2. **`dedupe`** — Hash-based dedup against content hashes already in Postgres. Same concept as the current `caption.py` hash check, now against the hosted DB instead of local SQLite.

3. **`classify`** — Two-part quality/content pre-filter, replacing the current single fragile CLIP classifier:
   - **Cheap heuristics** (near-zero cost): resolution check (existing `MIN_WIDTH`/`MIN_HEIGHT` logic), blur detection (Laplacian variance), aspect-ratio sanity.
   - **CLIP zero-shot content-type gate**: scores each candidate against individual prompts (max similarity per prompt, *not* an averaged prototype vector — the current implementation's core bug, which blends orthogonal concepts like "blurry" and "character reference sheet" into one meaningless centroid). Used only to gate content type (painting vs. sketch/character-sheet/meme/photo) and control how many images proceed to the paid captioning stage — not to make subjective quality/mood judgments, which CLIP handles poorly.

4. **`caption`** — Calls a provider-agnostic `analyze_image()` interface (default implementation: Gemini Flash) that produces title, caption, tags, and scores via the existing JSON schema, **plus a new `keep`/`rejection_reason` field** — Gemini's vision reasoning does the final quality/relevance gate that CLIP was unreliably attempting, since it's already looking at the full image. Includes strict JSON-schema validation with retry-on-malformed-output, since this call now also gates content into the dataset (a schema violation here is more consequential than before).

5. **`embed`** — Generates the text embedding for cross-modal search (`text-embedding-004`, same approach as current `vectordb.py`).

6. **`persist`** — Uploads the image to R2 and writes one row to Postgres (metadata + `pgvector` column) in a single transaction per image, so a mid-run failure never leaves an orphaned upload or a half-written row.

Each stage is an independently testable module with a clear input/output contract — not one monolithic script like the current `caption.py`, which mixes hashing, DB access, and Gemini calls together.

## Provider-agnostic captioning interface

`analyze_image(image) -> AnalysisResult` is the stage's public contract. Gemini Flash is the default implementation, chosen for cost at this run volume (scheduled/repeated, free-tier-friendly) — but the interface exists so a provider can be swapped without touching the rest of the pipeline, and so a future small eval script (comparing caption quality/schema-adherence/cost across providers) is cheap to build later as a standalone artifact. Not building the eval harness now — YAGNI until there's a reason to compare.

## Error handling

- Per-image `try`/`except` in every stage — one bad image (corrupt file, API timeout, malformed JSON) logs and is skipped; it never aborts the run.
- `persist` is the only stage touching durable state, and does so in one transaction per image (upload + DB row) — mirrors the current `caption.py` per-image-commit pattern. A failed run leaves no orphaned state; the next scheduled run resumes naturally via the `dedupe` hash check.
- A whole-job crash in GitHub Actions is safe by construction — nothing partial persists, and re-runs pick up where dedup leaves off.

## Rate limiting & backoff

| API | Known limit | Handling |
|---|---|---|
| Reddit (PRAW) | ~100 QPM per OAuth client; PRAW auto-throttles from response headers | Mostly self-managing. Per-subreddit try/except — one subreddit failing logs and moves on rather than aborting the scrape stage. |
| DeviantArt | Undocumented precisely; enforced via 429 | Exponential backoff on 429 (capped retries), then skip remaining DeviantArt work for the run rather than blocking Reddit or downstream stages. |
| Gemini (caption + embed) | Free tier: ~15 RPM, ~1500 RPD — the tightest constraint in the pipeline | Centralized token-bucket rate limiter shared across caption + embed calls (replacing today's scattered `time.sleep(5)` calls). Exponential backoff on 429. **Daily-quota exhaustion is a clean stop, not an error**: the stage stops pulling new images but everything already persisted in the run stays committed; the next scheduled run continues from there. `images-per-run` is capped comfortably under the daily quota so one run can't exhaust the day's budget and starve error-recovery retries. |
| R2 / Supabase Postgres | Generous (thousands of req/s) — not a practical constraint at this volume | Standard transient-failure retry (few attempts, short backoff) for network blips — resilience, not rate-limit avoidance. |

## Config & secrets

- All credentials as GitHub Actions repo secrets: `REDDIT_*`, `DEVIANTART_*`, `GOOGLE_API_KEY`, `DATABASE_URL`, R2 access keys.
- Non-secret tunables (subreddit list, DeviantArt tags/queries, images-per-run cap, CLIP thresholds, cron cadence) live in a checked-in config file — not hardcoded scattered constants as in the current scripts.

## Testing

- Each stage module gets unit tests with mocked external calls (Reddit/DeviantArt APIs, Gemini API, R2, Postgres) — newly possible because stages are separated, unlike the current monolithic `caption.py`.
- No integration test hits real external APIs in CI (cost/flakiness risk). Verification before merging pipeline changes is a local manual run against real APIs.

## Open items for a later sub-project

- ML/recommendation core (embeddings quality, cross-modal matching) — separate spec.
- Backend API changes needed to read from Postgres/R2 instead of SQLite/local disk — separate spec, but this pipeline's storage choice is a hard dependency for that work.
- Frontend and deployment/infra — separate specs.
