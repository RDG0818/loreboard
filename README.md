# Loreboard

Loreboard is a Magic: The Gathering card discovery app — a Pinterest-style browsing feed for card art, backed by a content-based recommendation system and natural-language search, built on Scryfall's public card database.

## Core Features/Technical Stack

- **Scryfall Bulk Ingestion**: A scheduled pipeline downloads Scryfall's card database (unique artwork) and syncs it into Postgres, with text embeddings generated via the Gemini API for every card.

- **Masonry Card Browsing**: An infinite-scroll, art-focused feed (no login required to browse, per Scryfall's Fan Content Policy) built with vanilla JS and Masonry.

- **Google OAuth Accounts**: Sign in to save cards and build a personalized recommendation profile.

- **Content-Based Recommendations**: A user's saved cards are averaged into a taste vector and matched against all card embeddings via pgvector nearest-neighbor search.

- **Natural-Language Search**: An LLM translates free-text requests ("low cost commanders that draw cards") into structured card search queries.

- **Backend**: FastAPI, Postgres + pgvector.

## Database Migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/) (`backend/db/migrations/`). `DATABASE_URL` is read the same way the app reads it (env var) — no separate credential in `alembic.ini`.

- Apply all pending migrations: `alembic upgrade head`
- Create a new migration: `alembic revision -m "describe the change"`, then hand-write the SQL in the generated file's `upgrade()`/`downgrade()`.

Fresh local setup requires running `alembic upgrade head` once before first use — the app and ingest pipeline no longer apply schema automatically.

## Future Development

- Collaborative filtering, once real usage data accumulates. The `views` table and the `POST /api/v1/views` endpoint exist and are tested, but the frontend does not call the endpoint yet, so no view events are being recorded — wiring that up is a prerequisite.
- Native/PWA mobile client.
- Passive view-weighted signal in the recommender, alongside explicit saves.
