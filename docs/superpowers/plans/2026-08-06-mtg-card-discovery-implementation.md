# MTG Card Discovery App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Loreboard's fantasy-art scraping pipeline with a Magic: The Gathering card discovery app — Scryfall bulk-data ingestion into Postgres+pgvector, a masonry browsing feed, Google OAuth accounts, content-based recommendations, and natural-language search.

**Architecture:** FastAPI backend (Postgres+pgvector, no object storage — card images hotlink from `cards.scryfall.io`), evolving the existing Vite + vanilla JS masonry frontend. A scheduled GitHub Actions job bulk-ingests Scryfall's card data and backfills text embeddings via the existing Gemini-based `embed.py`. Recommendations are computed on the fly (no persisted user-embedding state) via pgvector nearest-neighbor search against a taste vector averaged from a user's saved cards.

**Tech Stack:** FastAPI, psycopg2 + pgvector, Authlib (Google OAuth), google-generativeai (embeddings + NL-search translation), numpy, Vite + vanilla JS (masonry-layout, imagesloaded).

## Global Constraints

- No R2/object storage anywhere in this project — card images are hotlinked directly from `cards.scryfall.io` (confirmed no rate limit on that host, per Scryfall's docs).
- Browsing endpoints (`GET /api/v1/cards`, `GET /api/v1/cards/search`, `GET /api/v1/cards/{id}`, `GET /api/v1/cards/{id}/similar`, `POST /api/v1/search/natural`) never require auth — Scryfall's Fan Content Policy requires anonymous or free-account access to card data.
- Auth is Google OAuth only — no password storage or handling anywhere.
- Recommendations are content-based only in this phase — no collaborative filtering (deferred; `views` table exists to seed it later).
- The taste vector is computed from `saves` only. `views` are logged (`POST /api/v1/views`) but not read by the recommender in this phase.
- No DB connection pooling — one `psycopg2` connection opened and closed per request. Acceptable at this project's scale; a documented simplification, not an oversight.
- `backend/pipeline/embed.py`, `rate_limit.py`, `gemini_retry.py`, and `db.py`'s `get_connection()` (extension-then-register_vector bootstrap) are reused unchanged.
- pgvector embedding dimension is 768 (`text-embedding-004`'s output size — matches the dimension already used in the old `images` table).
- Every card art display in the frontend must show the artist's name (Scryfall Fan Content Policy requirement).
- Tests always run via `./.venv/bin/python -m pytest backend/pipeline/ -q` (or the relevant subpath) — never a bare `pytest`, which can silently resolve to the wrong interpreter on this machine.

---

### Task 1: Postgres schema for cards/users/saves/views

**Files:**
- Modify: `backend/pipeline/db.py`
- Modify: `backend/pipeline/tests/test_db.py`

**Interfaces:**
- Produces: `db.get_connection()` (unchanged signature, still returns a psycopg2 connection with the `vector` extension bootstrapped and `register_vector` applied), `db.init_schema(conn) -> None` (now creates `cards`, `users`, `saves`, `views` instead of `images`).

- [ ] **Step 1: Write the failing tests**

Replace the art-specific tests in `backend/pipeline/tests/test_db.py` (`test_hash_exists_*`, `test_insert_image_*`, `test_insert_sql_has_on_conflict_do_nothing_guard`) — those functions no longer exist. Keep `test_get_connection_creates_extension_before_registering_vector` exactly as-is (that behavior is unchanged). Add:

```python
def test_init_schema_creates_expected_tables():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    db.init_schema(conn)

    executed_sql = cursor.execute.call_args[0][0]
    for table in ("cards", "users", "saves", "views"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in executed_sql
    conn.commit.assert_called_once()
```

The final `test_db.py` should contain only: `test_get_connection_creates_extension_before_registering_vector` and `test_init_schema_creates_expected_tables`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_db.py -v`
Expected: `test_init_schema_creates_expected_tables` FAILS (old schema doesn't have these tables); other art-specific tests are gone so nothing to fail there.

- [ ] **Step 3: Rewrite `db.py`**

```python
import os

import psycopg2
from pgvector.psycopg2 import register_vector

CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"

SCHEMA_SQL = """
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
    embedding vector(768)
);

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


def init_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_db.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/db.py backend/pipeline/tests/test_db.py
git commit -m "feat: replace fantasy-art schema with cards/users/saves/views tables"
```

---

### Task 2: Cards repository

**Files:**
- Create: `backend/pipeline/cards.py`
- Create: `backend/pipeline/tests/test_cards.py`

**Interfaces:**
- Consumes: nothing from other new modules (only `psycopg2.extras`).
- Produces: `card_row_from_json(card: dict) -> dict`, `upsert_card(conn, row: dict) -> None`, `iter_missing_embeddings(conn) -> Iterator[tuple[str, str]]`, `set_card_embedding(conn, card_id: str, embedding: list[float]) -> None`, `get_card_embedding(conn, card_id: str) -> list[float] | None`, `fetch_cards_page(conn, cursor: str | None, limit: int = 30) -> list[dict]`, `get_card(conn, card_id: str) -> dict | None`, `search_cards(conn, where_sql: str, params: list, limit: int = 60) -> list[dict]`, `nearest_neighbors(conn, embedding: list[float], limit: int = 20, exclude_card_id: str | None = None) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock
import psycopg2.extras
from backend.pipeline import cards


def test_card_row_from_json_single_faced_card():
    raw = {
        "id": "abc-123",
        "name": "Identity Thief",
        "oracle_text": "Whenever this creature attacks...",
        "type_line": "Creature — Shapeshifter",
        "mana_cost": "{2}{U}{U}",
        "cmc": 4.0,
        "colors": ["U"],
        "color_identity": ["U"],
        "legalities": {"modern": "legal"},
        "artist": "Some Artist",
        "image_uris": {"art_crop": "https://cards.scryfall.io/art_crop/x.jpg"},
    }
    row = cards.card_row_from_json(raw)
    assert row["id"] == "abc-123"
    assert row["oracle_text"] == "Whenever this creature attacks..."
    assert row["colors"] == ["U"]


def test_card_row_from_json_double_faced_card_falls_back_to_faces():
    raw = {
        "id": "df-1",
        "name": "Front // Back",
        "type_line": "Creature // Creature",
        "card_faces": [
            {"oracle_text": "Front text", "colors": ["W"], "image_uris": {"art_crop": "https://x/front.jpg"}},
            {"oracle_text": "Back text", "colors": ["B"]},
        ],
    }
    row = cards.card_row_from_json(raw)
    assert row["oracle_text"] == "Front text // Back text"
    assert row["colors"] == ["W"]
    assert row["image_uris"].adapted == {"art_crop": "https://x/front.jpg"}


def test_upsert_card_executes_upsert_sql():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    row = {
        "id": "c1", "name": "N", "oracle_text": None, "type_line": None,
        "mana_cost": None, "cmc": None, "colors": None, "color_identity": None,
        "legalities": psycopg2.extras.Json({}), "artist": None, "image_uris": None,
    }
    cards.upsert_card(conn, row)
    cursor.execute.assert_called_once()
    assert "ON CONFLICT (id) DO UPDATE" in cursor.execute.call_args[0][0]


def test_iter_missing_embeddings_builds_text_from_row():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("c1", "Bolt", "Instant", "Deal 3 damage")]

    results = list(cards.iter_missing_embeddings(conn))

    assert results == [("c1", "Bolt. Instant. Deal 3 damage")]
    assert "WHERE embedding IS NULL" in cursor.execute.call_args[0][0]


def test_set_card_embedding_executes_update():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cards.set_card_embedding(conn, "c1", [0.1, 0.2])
    cursor.execute.assert_called_once_with("UPDATE cards SET embedding = %s WHERE id = %s", ([0.1, 0.2], "c1"))


def test_get_card_embedding_returns_none_when_missing():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    assert cards.get_card_embedding(conn, "missing") is None


def test_nearest_neighbors_excludes_given_card_when_provided():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cards.nearest_neighbors(conn, [0.1, 0.2], limit=5, exclude_card_id="c1")
    sql = cursor.execute.call_args[0][0]
    assert "id != %s" in sql
```

Note: `test_card_row_from_json_double_faced_card_falls_back_to_faces` asserts `.adapted` on the `image_uris` field — `psycopg2.extras.Json` wraps a value and exposes it via `.adapted`. This is how the test verifies the wrapped dict without needing a real DB connection.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_cards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.cards'`

- [ ] **Step 3: Implement `cards.py`**

```python
import psycopg2.extras

UPSERT_SQL = """
INSERT INTO cards (id, name, oracle_text, type_line, mana_cost, cmc, colors, color_identity, legalities, artist, image_uris)
VALUES (%(id)s, %(name)s, %(oracle_text)s, %(type_line)s, %(mana_cost)s, %(cmc)s, %(colors)s, %(color_identity)s, %(legalities)s, %(artist)s, %(image_uris)s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    oracle_text = EXCLUDED.oracle_text,
    type_line = EXCLUDED.type_line,
    mana_cost = EXCLUDED.mana_cost,
    cmc = EXCLUDED.cmc,
    colors = EXCLUDED.colors,
    color_identity = EXCLUDED.color_identity,
    legalities = EXCLUDED.legalities,
    artist = EXCLUDED.artist,
    image_uris = EXCLUDED.image_uris
"""

CARD_LIST_COLUMNS = "id, name, artist, image_uris"


def card_row_from_json(card: dict) -> dict:
    """Maps a raw Scryfall card object (from the bulk JSONL dump) to our row
    shape. Double-faced cards store oracle text/images/colors per-face
    instead of at the top level, so fall back to the front face."""
    oracle_text = card.get("oracle_text")
    image_uris = card.get("image_uris")
    colors = card.get("colors")
    faces = card.get("card_faces") or []

    if oracle_text is None and faces:
        oracle_text = " // ".join(f.get("oracle_text", "") for f in faces).strip() or None
    if image_uris is None and faces:
        image_uris = faces[0].get("image_uris")
    if colors is None and faces:
        colors = faces[0].get("colors")

    return {
        "id": card["id"],
        "name": card["name"],
        "oracle_text": oracle_text,
        "type_line": card.get("type_line"),
        "mana_cost": card.get("mana_cost"),
        "cmc": card.get("cmc"),
        "colors": colors,
        "color_identity": card.get("color_identity"),
        "legalities": psycopg2.extras.Json(card.get("legalities") or {}),
        "artist": card.get("artist"),
        "image_uris": psycopg2.extras.Json(image_uris) if image_uris else None,
    }


def upsert_card(conn, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(UPSERT_SQL, row)


def iter_missing_embeddings(conn):
    """Yields (card_id, embedding_text) for every card without an embedding."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, type_line, oracle_text FROM cards WHERE embedding IS NULL")
        rows = cur.fetchall()
    for card_id, name, type_line, oracle_text in rows:
        yield card_id, f"{name}. {type_line or ''}. {oracle_text or ''}"


def set_card_embedding(conn, card_id: str, embedding: list[float]) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE cards SET embedding = %s WHERE id = %s", (embedding, card_id))


def get_card_embedding(conn, card_id: str) -> list[float] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT embedding FROM cards WHERE id = %s", (card_id,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_cards_page(conn, cursor: str | None, limit: int = 30) -> list[dict]:
    """Cursor-paginated card feed, ordered by id for stable pagination."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if cursor:
            cur.execute(
                f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE id > %s ORDER BY id LIMIT %s",
                (cursor, limit),
            )
        else:
            cur.execute(f"SELECT {CARD_LIST_COLUMNS} FROM cards ORDER BY id LIMIT %s", (limit,))
        return cur.fetchall()


def get_card(conn, card_id: str) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, oracle_text, type_line, mana_cost, artist, image_uris FROM cards WHERE id = %s",
            (card_id,),
        )
        return cur.fetchone()


def search_cards(conn, where_sql: str, params: list, limit: int = 60) -> list[dict]:
    query = f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE {where_sql} ORDER BY name LIMIT %s"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params + [limit])
        return cur.fetchall()


def nearest_neighbors(conn, embedding: list[float], limit: int = 20, exclude_card_id: str | None = None) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if exclude_card_id:
            cur.execute(
                f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE embedding IS NOT NULL AND id != %s "
                "ORDER BY embedding <=> %s LIMIT %s",
                (exclude_card_id, embedding, limit),
            )
        else:
            cur.execute(
                f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> %s LIMIT %s",
                (embedding, limit),
            )
        return cur.fetchall()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_cards.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/cards.py backend/pipeline/tests/test_cards.py
git commit -m "feat: add cards repository (upsert, pagination, search, nearest-neighbor)"
```

---

### Task 3: Users and interactions repositories

**Files:**
- Create: `backend/pipeline/users.py`
- Create: `backend/pipeline/interactions.py`
- Create: `backend/pipeline/tests/test_users.py`
- Create: `backend/pipeline/tests/test_interactions.py`

**Interfaces:**
- Produces: `users.get_or_create_user(conn, google_sub: str, email: str) -> dict`, `users.get_user_by_id(conn, user_id: int) -> dict | None`, `interactions.add_save(conn, user_id: int, card_id: str) -> None`, `interactions.remove_save(conn, user_id: int, card_id: str) -> None`, `interactions.list_saves(conn, user_id: int) -> list[dict]`, `interactions.list_saved_card_embeddings(conn, user_id: int) -> list[list[float]]`, `interactions.log_views(conn, user_id: int, card_ids: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/pipeline/tests/test_users.py
from unittest.mock import MagicMock
from backend.pipeline import users


def test_get_or_create_user_returns_existing_row_without_inserting():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"id": 1, "google_sub": "sub1", "email": "a@b.com"}

    result = users.get_or_create_user(conn, "sub1", "a@b.com")

    assert result == {"id": 1, "google_sub": "sub1", "email": "a@b.com"}
    assert cursor.execute.call_count == 1  # only the SELECT, no INSERT


def test_get_or_create_user_inserts_when_not_found():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [None, {"id": 2, "google_sub": "sub2", "email": "c@d.com"}]

    result = users.get_or_create_user(conn, "sub2", "c@d.com")

    assert result == {"id": 2, "google_sub": "sub2", "email": "c@d.com"}
    assert cursor.execute.call_count == 2  # SELECT then INSERT


def test_get_user_by_id_returns_none_when_missing():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    assert users.get_user_by_id(conn, 999) is None
```

```python
# backend/pipeline/tests/test_interactions.py
from unittest.mock import MagicMock
from backend.pipeline import interactions


def test_add_save_uses_on_conflict_do_nothing():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    interactions.add_save(conn, 1, "card-1")
    sql = cursor.execute.call_args[0][0]
    assert "ON CONFLICT DO NOTHING" in sql


def test_remove_save_deletes_by_user_and_card():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    interactions.remove_save(conn, 1, "card-1")
    cursor.execute.assert_called_once_with(
        "DELETE FROM saves WHERE user_id = %s AND card_id = %s", (1, "card-1")
    )


def test_list_saved_card_embeddings_filters_null_embeddings_in_sql():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [([0.1, 0.2],), ([0.3, 0.4],)]

    result = interactions.list_saved_card_embeddings(conn, 1)

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert "c.embedding IS NOT NULL" in cursor.execute.call_args[0][0]


def test_log_views_batches_all_card_ids():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    interactions.log_views(conn, 1, ["c1", "c2", "c3"])
    args = cursor.executemany.call_args[0]
    assert args[1] == [(1, "c1"), (1, "c2"), (1, "c3")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_users.py backend/pipeline/tests/test_interactions.py -v`
Expected: FAIL with `ModuleNotFoundError` for both modules.

- [ ] **Step 3: Implement `users.py` and `interactions.py`**

```python
# backend/pipeline/users.py
import psycopg2.extras


def get_or_create_user(conn, google_sub: str, email: str) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, google_sub, email FROM users WHERE google_sub = %s", (google_sub,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute(
            "INSERT INTO users (google_sub, email) VALUES (%s, %s) RETURNING id, google_sub, email",
            (google_sub, email),
        )
        return cur.fetchone()


def get_user_by_id(conn, user_id: int) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, google_sub, email FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()
```

```python
# backend/pipeline/interactions.py
import psycopg2.extras


def add_save(conn, user_id: int, card_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO saves (user_id, card_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, card_id),
        )


def remove_save(conn, user_id: int, card_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM saves WHERE user_id = %s AND card_id = %s", (user_id, card_id))


def list_saves(conn, user_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT c.id, c.name, c.artist, c.image_uris FROM saves s "
            "JOIN cards c ON c.id = s.card_id WHERE s.user_id = %s ORDER BY s.saved_at DESC",
            (user_id,),
        )
        return cur.fetchall()


def list_saved_card_embeddings(conn, user_id: int) -> list[list[float]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.embedding FROM saves s JOIN cards c ON c.id = s.card_id "
            "WHERE s.user_id = %s AND c.embedding IS NOT NULL",
            (user_id,),
        )
        return [row[0] for row in cur.fetchall()]


def log_views(conn, user_id: int, card_ids: list[str]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO views (user_id, card_id) VALUES (%s, %s)",
            [(user_id, cid) for cid in card_ids],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_users.py backend/pipeline/tests/test_interactions.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/users.py backend/pipeline/interactions.py backend/pipeline/tests/test_users.py backend/pipeline/tests/test_interactions.py
git commit -m "feat: add users and interactions (saves/views) repositories"
```

---

### Task 4: Scryfall ingestion orchestrator + remove dead pipeline code

**Files:**
- Modify: `backend/pipeline/config.py`
- Modify: `backend/pipeline/tests/test_config.py`
- Modify: `backend/pipeline/run.py`
- Modify: `backend/pipeline/tests/test_run.py`
- Modify: `backend/requirements.txt`
- Modify: `.github/workflows/data_pipeline.yml`
- Delete: `backend/pipeline/scrape_deviantart.py`, `backend/pipeline/scrape_artstation.py`, `backend/pipeline/classify_clip.py`, `backend/pipeline/classify_heuristics.py`, `backend/pipeline/caption.py`, `backend/pipeline/caption_gemini.py`, `backend/pipeline/dedupe.py`, `backend/pipeline/persist.py`, `backend/pipeline/storage.py`, `backend/pipeline/types.py`, and their corresponding files in `backend/pipeline/tests/`

**Interfaces:**
- Consumes: `cards.card_row_from_json`, `cards.upsert_card`, `cards.iter_missing_embeddings`, `cards.set_card_embedding` (Task 2); `db.get_connection`, `db.init_schema` (Task 1); `embed.build_embedder` (unchanged, existing); `rate_limit.RateLimiter`, `rate_limit.DailyQuota`, `rate_limit.DailyQuotaExceeded` (unchanged, existing).
- Produces: `run.ingest_cards(conn, session=requests) -> int`, `run.backfill_embeddings(conn, cfg) -> int`, `run.run() -> None`.

- [ ] **Step 1: Delete the dead pipeline files**

```bash
git rm backend/pipeline/scrape_deviantart.py backend/pipeline/scrape_artstation.py \
       backend/pipeline/classify_clip.py backend/pipeline/classify_heuristics.py \
       backend/pipeline/caption.py backend/pipeline/caption_gemini.py \
       backend/pipeline/dedupe.py backend/pipeline/persist.py backend/pipeline/storage.py \
       backend/pipeline/types.py \
       backend/pipeline/tests/test_scrape_deviantart.py backend/pipeline/tests/test_scrape_artstation.py \
       backend/pipeline/tests/test_classify_clip.py backend/pipeline/tests/test_classify_heuristics.py \
       backend/pipeline/tests/test_caption.py backend/pipeline/tests/test_caption_gemini.py \
       backend/pipeline/tests/test_dedupe.py backend/pipeline/tests/test_persist.py \
       backend/pipeline/tests/test_storage.py backend/pipeline/tests/test_types.py
```

- [ ] **Step 2: Rewrite `config.py`**

Strip to only the fields `embed.py` actually reads.

```python
import dataclasses
import os


@dataclasses.dataclass
class PipelineConfig:
    gemini_rpm: int
    gemini_rpd: int


DEFAULT_CONFIG = PipelineConfig(
    gemini_rpm=15,
    gemini_rpd=1200,  # capped comfortably under the 1500/day free-tier limit
)


def load_config() -> PipelineConfig:
    return DEFAULT_CONFIG
```

Update `backend/pipeline/tests/test_config.py`:

```python
from backend.pipeline.config import load_config, PipelineConfig


def test_load_config_returns_defaults():
    cfg = load_config()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.gemini_rpm == 15
    assert cfg.gemini_rpd == 1200
```

(The old `PIPELINE_IMAGES_PER_RUN` env-var override is removed along with the field it controlled — ingestion now processes the full bulk dump, not a capped run.)

- [ ] **Step 3: Write the failing tests for `run.py`**

Replace `backend/pipeline/tests/test_run.py` entirely:

```python
from unittest.mock import MagicMock
from backend.pipeline import run
from backend.pipeline.rate_limit import DailyQuotaExceeded


def test_find_bulk_download_uri_returns_matching_entry():
    session = MagicMock()
    session.get.return_value.json.return_value = {
        "data": [
            {"type": "oracle_cards", "jsonl_download_uri": "https://x/oracle.jsonl.gz"},
            {"type": "unique_artwork", "jsonl_download_uri": "https://x/unique-artwork.jsonl.gz"},
        ]
    }
    session.get.return_value.raise_for_status.return_value = None

    uri = run._find_bulk_download_uri(session=session)

    assert uri == "https://x/unique-artwork.jsonl.gz"


def test_find_bulk_download_uri_raises_when_type_missing():
    session = MagicMock()
    session.get.return_value.json.return_value = {"data": []}
    session.get.return_value.raise_for_status.return_value = None

    try:
        run._find_bulk_download_uri(session=session)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_ingest_cards_upserts_each_row_and_isolates_bad_rows(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(run, "_find_bulk_download_uri", lambda session: "https://x/data.jsonl.gz")
    monkeypatch.setattr(
        run,
        "_iter_bulk_cards",
        lambda uri, session: iter([
            {"id": "c1", "name": "Good Card"},
            {"name": "Missing ID"},  # malformed — no "id" key, must be skipped not crash the run
            {"id": "c2", "name": "Another Good Card"},
        ]),
    )
    upserted = []
    monkeypatch.setattr(run.cards, "upsert_card", lambda conn, row: upserted.append(row["id"]))

    count = run.ingest_cards(conn)

    assert count == 2
    assert upserted == ["c1", "c2"]
    conn.commit.assert_called()


def test_backfill_embeddings_stops_cleanly_on_daily_quota(monkeypatch):
    conn = MagicMock()
    cfg = MagicMock(gemini_rpm=15, gemini_rpd=1200)
    monkeypatch.setattr(
        run.cards, "iter_missing_embeddings", lambda conn: iter([("c1", "text1"), ("c2", "text2")])
    )
    embedder = MagicMock()
    embedder.embed_text.side_effect = [[0.1, 0.2], DailyQuotaExceeded("quota gone")]
    monkeypatch.setattr(run, "build_embedder", lambda cfg, *a, **k: embedder)
    set_calls = []
    monkeypatch.setattr(run.cards, "set_card_embedding", lambda conn, cid, emb: set_calls.append(cid))

    embedded = run.backfill_embeddings(conn, cfg)

    assert embedded == 1
    assert set_calls == ["c1"]


def test_backfill_embeddings_skips_candidate_on_generic_exception(monkeypatch):
    conn = MagicMock()
    cfg = MagicMock(gemini_rpm=15, gemini_rpd=1200)
    monkeypatch.setattr(
        run.cards, "iter_missing_embeddings", lambda conn: iter([("c1", "text1"), ("c2", "text2")])
    )
    embedder = MagicMock()
    embedder.embed_text.side_effect = [RuntimeError("boom"), [0.3, 0.4]]
    monkeypatch.setattr(run, "build_embedder", lambda cfg, *a, **k: embedder)
    set_calls = []
    monkeypatch.setattr(run.cards, "set_card_embedding", lambda conn, cid, emb: set_calls.append(cid))

    embedded = run.backfill_embeddings(conn, cfg)

    assert embedded == 1
    assert set_calls == ["c2"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_run.py -v`
Expected: FAIL — `run.py` still has the old scrape/classify/caption/embed/persist orchestration and none of these names exist yet.

- [ ] **Step 5: Rewrite `run.py`**

```python
import gzip
import json

import requests

from backend.pipeline import cards
from backend.pipeline import db
from backend.pipeline.config import load_config
from backend.pipeline.embed import build_embedder
from backend.pipeline.rate_limit import DailyQuota, DailyQuotaExceeded, RateLimiter

BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
HEADERS = {"User-Agent": "loreboard-mtg-pipeline/1.0", "Accept": "application/json"}
BULK_DATA_TYPE = "unique_artwork"
COMMIT_BATCH_SIZE = 500


def _find_bulk_download_uri(bulk_type: str = BULK_DATA_TYPE, session=requests) -> str:
    response = session.get(BULK_DATA_URL, headers=HEADERS)
    response.raise_for_status()
    for entry in response.json()["data"]:
        if entry["type"] == bulk_type:
            return entry["jsonl_download_uri"]
    raise ValueError(f"No bulk-data entry found for type {bulk_type!r}")


def _iter_bulk_cards(download_uri: str, session=requests):
    response = session.get(download_uri, headers=HEADERS, stream=True)
    response.raise_for_status()
    with gzip.GzipFile(fileobj=response.raw) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def ingest_cards(conn, session=requests) -> int:
    download_uri = _find_bulk_download_uri(session=session)
    count = 0
    for raw_card in _iter_bulk_cards(download_uri, session=session):
        try:
            row = cards.card_row_from_json(raw_card)
            cards.upsert_card(conn, row)
            count += 1
            if count % COMMIT_BATCH_SIZE == 0:
                conn.commit()
        except Exception as e:
            print(f"Ingestion: skipping malformed card record: {e}")
            continue
    conn.commit()
    return count


def backfill_embeddings(conn, cfg) -> int:
    rate_limiter = RateLimiter(calls_per_minute=cfg.gemini_rpm)
    daily_quota = DailyQuota(max_calls_per_day=cfg.gemini_rpd)
    embedder = build_embedder(cfg, rate_limiter, daily_quota)

    embedded = 0
    for card_id, text in cards.iter_missing_embeddings(conn):
        try:
            embedding = embedder.embed_text(text)
            cards.set_card_embedding(conn, card_id, embedding)
            conn.commit()
            embedded += 1
        except DailyQuotaExceeded:
            print("Daily Gemini quota exhausted — stopping embedding backfill; already-embedded cards are saved.")
            break
        except Exception as e:
            print(f"Embedding backfill: skipping card {card_id}: {e}")
            continue
    return embedded


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


if __name__ == "__main__":
    run()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/pipeline/tests/test_run.py backend/pipeline/tests/test_config.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Trim `requirements.txt`**

Remove now-orphaned packages (verified zero remaining imports after the deletions in Step 1: `sentence-transformers` was only used by `classify_clip.py`; `pillow`/PIL only by the removed captioning/classification files; `tqdm` only by `vectordb.py`/`audio.py`/`caption.py`, all removed in Task 14; `boto3` only by `storage.py`; `mutagen`, `imagehash`, `ollama`, `timm`, `transformers`, `accelerate`, `pandas`, `python-multipart` had zero imports anywhere in the codebase already — pre-existing dead weight). Add `requests` and `google-api-core`, both used directly but previously only pulled in transitively. Also add `authlib` and `itsdangerous` (needed by Task 6's OAuth work — added now to keep this one dependency-cleanup pass complete).

Final `backend/requirements.txt`:

```
fastapi
uvicorn
numpy
python-dotenv
google-generativeai
google-api-core
requests
psycopg2-binary
pgvector
authlib
itsdangerous
pytest
```

- [ ] **Step 8: Update the GitHub Actions workflow**

Edit `.github/workflows/data_pipeline.yml` — remove the now-unused `DEVIANTART_CLIENT_ID`/`DEVIANTART_CLIENT_SECRET` env vars (Scryfall's bulk data and API need no auth at all):

```yaml
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: python -m backend.pipeline.run
```

- [ ] **Step 9: Run the full pipeline suite**

Run: `./.venv/bin/python -m pytest backend/pipeline/ -q`
Expected: PASS, no leftover references to deleted modules.

- [ ] **Step 10: Commit**

```bash
git add -A backend/pipeline backend/requirements.txt .github/workflows/data_pipeline.yml
git commit -m "feat: replace scrape/classify/caption pipeline with Scryfall bulk ingestion"
```

---

### Task 5: Structured search query parser

**Files:**
- Create: `backend/query_parser.py`
- Create: `backend/tests/test_query_parser.py`
- Create: `backend/tests/__init__.py` (empty — new test package alongside `backend/pipeline/tests/`)

**Interfaces:**
- Produces: `QueryParseError` (subclass of `ValueError`), `parse_query(query: str) -> tuple[str, list]`.

**Known limitation (explicitly scoped, not a bug):** `t:` and `o:` values must be single words — no quoted multi-word phrases. Task 6's NL-search prompt is written to only ever emit single-word `t:`/`o:` values, so this limitation never surfaces to users through that path. Documented here so it isn't mistaken for an oversight later.

- [ ] **Step 1: Write the failing tests**

```python
from backend.query_parser import QueryParseError, parse_query


def test_parse_cmc_comparison():
    sql, params = parse_query("cmc<=3")
    assert sql == "cmc <= %s"
    assert params == [3.0]


def test_parse_type_filter():
    sql, params = parse_query("t:legendary")
    assert sql == "type_line ILIKE %s"
    assert params == ["%legendary%"]


def test_parse_oracle_text_filter():
    sql, params = parse_query("o:draw")
    assert sql == "oracle_text ILIKE %s"
    assert params == ["%draw%"]


def test_parse_colors_filter_uppercases_letters():
    sql, params = parse_query("c:wu")
    assert sql == "colors @> %s"
    assert params == [["W", "U"]]


def test_parse_color_identity_filter():
    sql, params = parse_query("id:g")
    assert sql == "color_identity @> %s"
    assert params == [["G"]]


def test_parse_format_legality_filter():
    sql, params = parse_query("f:commander")
    assert sql == "legalities ->> %s = 'legal'"
    assert params == ["commander"]


def test_parse_bare_word_matches_name():
    sql, params = parse_query("Bolt")
    assert sql == "name ILIKE %s"
    assert params == ["%Bolt%"]


def test_parse_combines_multiple_tokens_with_and():
    sql, params = parse_query("cmc<=3 t:legendary o:draw")
    assert sql == "cmc <= %s AND type_line ILIKE %s AND oracle_text ILIKE %s"
    assert params == [3.0, "%legendary%", "%draw%"]


def test_parse_empty_query_raises():
    try:
        parse_query("   ")
        assert False, "expected QueryParseError"
    except QueryParseError:
        pass


def test_parse_unrecognized_operator_raises():
    try:
        parse_query("xyz:something")
        assert False, "expected QueryParseError"
    except QueryParseError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_query_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.query_parser'`

- [ ] **Step 3: Implement `query_parser.py`**

```python
import re

_CMC_RE = re.compile(r"^cmc(<=|>=|<|>|=)(\d+(?:\.\d+)?)$")
_TYPE_RE = re.compile(r"^t:(\S+)$")
_ORACLE_RE = re.compile(r"^o:(\S+)$")
_COLOR_RE = re.compile(r"^c:([wubrg]+)$", re.IGNORECASE)
_IDENTITY_RE = re.compile(r"^id:([wubrg]+)$", re.IGNORECASE)
_FORMAT_RE = re.compile(r"^f:(\w+)$")

_CMC_OPS = {"<=": "<=", ">=": ">=", "<": "<", ">": ">", "=": "="}


class QueryParseError(ValueError):
    pass


def parse_query(query: str) -> tuple[str, list]:
    """Parses a small subset of Scryfall's search grammar into a
    parameterized SQL WHERE fragment + params. All values are parameterized
    (never string-interpolated) — safe against SQL injection.

    Supported: cmc<=N / cmc>=N / cmc<N / cmc>N / cmc=N, t:WORD, o:WORD
    (single word only — see module docstring in the implementation plan for
    why), c:WUBRG, id:WUBRG, f:FORMAT. Bare tokens match card name.
    """
    tokens = query.strip().split()
    if not tokens:
        raise QueryParseError("empty query")

    clauses = []
    params: list = []

    for token in tokens:
        m = _CMC_RE.match(token)
        if m:
            op, value = m.groups()
            clauses.append(f"cmc {_CMC_OPS[op]} %s")
            params.append(float(value))
            continue

        m = _TYPE_RE.match(token)
        if m:
            clauses.append("type_line ILIKE %s")
            params.append(f"%{m.group(1)}%")
            continue

        m = _ORACLE_RE.match(token)
        if m:
            clauses.append("oracle_text ILIKE %s")
            params.append(f"%{m.group(1)}%")
            continue

        m = _COLOR_RE.match(token)
        if m:
            clauses.append("colors @> %s")
            params.append([c.upper() for c in m.group(1)])
            continue

        m = _IDENTITY_RE.match(token)
        if m:
            clauses.append("color_identity @> %s")
            params.append([c.upper() for c in m.group(1)])
            continue

        m = _FORMAT_RE.match(token)
        if m:
            clauses.append("legalities ->> %s = 'legal'")
            params.append(m.group(1))
            continue

        if ":" in token:
            raise QueryParseError(f"unrecognized query token: {token!r}")

        clauses.append("name ILIKE %s")
        params.append(f"%{token}%")

    return " AND ".join(clauses), params
```

Create empty `backend/tests/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_query_parser.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/query_parser.py backend/tests/
git commit -m "feat: add structured card search query parser"
```

---

### Task 6: Natural-language search translation

**Files:**
- Create: `backend/nl_search.py`
- Create: `backend/tests/test_nl_search.py`

**Interfaces:**
- Consumes: `query_parser.QueryParseError`, `query_parser.parse_query` (Task 5).
- Produces: `translate_natural_language_query(text: str, model=None) -> str`, `resolve_search_query(text: str, model=None) -> tuple[str, list]`.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock
from backend.nl_search import resolve_search_query, translate_natural_language_query


def test_translate_natural_language_query_returns_stripped_model_text():
    model = MagicMock()
    model.generate_content.return_value.text = "  cmc<=3 t:legendary o:draw  \n"

    result = translate_natural_language_query("cheap legendary draw cards", model=model)

    assert result == "cmc<=3 t:legendary o:draw"


def test_resolve_search_query_parses_valid_translation():
    model = MagicMock()
    model.generate_content.return_value.text = "cmc<=3"

    sql, params = resolve_search_query("cheap stuff", model=model)

    assert sql == "cmc <= %s"
    assert params == [3.0]


def test_resolve_search_query_falls_back_on_invalid_translation():
    model = MagicMock()
    model.generate_content.return_value.text = "not a valid query!!"

    sql, params = resolve_search_query("something weird", model=model)

    assert sql == "(name ILIKE %s OR oracle_text ILIKE %s)"
    assert params == ["%something weird%", "%something weird%"]


def test_resolve_search_query_falls_back_when_model_call_raises():
    model = MagicMock()
    model.generate_content.side_effect = RuntimeError("API down")

    sql, params = resolve_search_query("anything", model=model)

    assert sql == "(name ILIKE %s OR oracle_text ILIKE %s)"
    assert params == ["%anything%", "%anything%"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_nl_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.nl_search'`

- [ ] **Step 3: Implement `nl_search.py`**

```python
import os

import google.generativeai as genai

from backend.query_parser import QueryParseError, parse_query

TRANSLATION_PROMPT = """Translate this Magic: The Gathering card search request into a compact query using ONLY this grammar, space-separated, one condition per token:

cmc<=N / cmc>=N / cmc<N / cmc>N / cmc=N   (mana value)
t:WORD       (card type contains WORD — single word only, no quotes or spaces)
o:WORD       (oracle text contains WORD — single word only, no quotes or spaces)
c:WUBRG      (colors, any combination of the letters W U B R G)
id:WUBRG     (color identity, e.g. for Commander)
f:FORMAT     (legal in FORMAT, e.g. f:commander, f:standard)
WORD         (bare word matches the card name)

Reply with ONLY the query, no explanation, no punctuation around it.

Example:
Request: "cheap legendary creatures that draw cards"
Reply: cmc<=3 t:legendary t:creature o:draw

Request: "{request}"
Reply:"""


def translate_natural_language_query(text: str, model=None) -> str:
    if model is None:
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
    response = model.generate_content(TRANSLATION_PROMPT.format(request=text))
    return response.text.strip()


def resolve_search_query(text: str, model=None) -> tuple[str, list]:
    """Translates natural language into the structured query grammar and
    parses it. Falls back to a plain name/oracle-text search on the raw
    input if the LLM call fails or its output doesn't parse — NL search
    should degrade to a basic search, never a hard error."""
    try:
        translated = translate_natural_language_query(text, model=model)
        return parse_query(translated)
    except Exception:
        return "(name ILIKE %s OR oracle_text ILIKE %s)", [f"%{text}%", f"%{text}%"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_nl_search.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/nl_search.py backend/tests/test_nl_search.py
git commit -m "feat: add LLM-driven natural-language search translation with fallback"
```

---

### Task 7: Google OAuth, session, and FastAPI app skeleton

**Files:**
- Create: `backend/auth.py`
- Create: `backend/tests/test_auth.py`
- Modify: `backend/main.py` (full rewrite)

**Interfaces:**
- Consumes: `users.get_or_create_user`, `users.get_user_by_id` (Task 3); `db.get_connection` (Task 1).
- Produces: `auth.router` (FastAPI `APIRouter`, mounted at no prefix — routes are `/auth/login/google` and `/auth/callback`), `auth.get_current_user(request) -> dict | None`, `auth.require_user(request) -> dict` (FastAPI dependency, raises `HTTPException(401)` when not logged in).

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from backend import auth


def test_get_current_user_returns_none_without_session():
    request = MagicMock()
    request.session = {}
    assert auth.get_current_user(request) is None


def test_get_current_user_looks_up_user_from_session(monkeypatch):
    request = MagicMock()
    request.session = {"user_id": 5}
    conn = MagicMock()
    monkeypatch.setattr(auth, "get_connection", lambda: conn)
    monkeypatch.setattr(auth.users, "get_user_by_id", lambda conn, uid: {"id": 5, "email": "a@b.com"})

    result = auth.get_current_user(request)

    assert result == {"id": 5, "email": "a@b.com"}
    conn.close.assert_called_once()


def test_require_user_raises_401_when_not_logged_in(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: None)

    with pytest.raises(HTTPException) as exc_info:
        auth.require_user(request)
    assert exc_info.value.status_code == 401


def test_require_user_returns_user_when_logged_in(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: {"id": 1})
    assert auth.require_user(request) == {"id": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.auth'`

- [ ] **Step 3: Implement `auth.py`**

```python
import os

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from backend.pipeline import users
from backend.pipeline.db import get_connection

router = APIRouter()

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/auth/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Google did not return user info")

    conn = get_connection()
    try:
        user = users.get_or_create_user(conn, userinfo["sub"], userinfo["email"])
        conn.commit()
    finally:
        conn.close()

    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/")


def get_current_user(request: Request) -> dict | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    conn = get_connection()
    try:
        return users.get_user_by_id(conn, user_id)
    finally:
        conn.close()


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user
```

Rewrite `backend/main.py`:

```python
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import router as auth_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET_KEY"])

app.include_router(auth_router)
```

(Tasks 8-10 each add one more `app.include_router(...)` line here.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/auth.py backend/tests/test_auth.py backend/main.py
git commit -m "feat: add Google OAuth login/callback and session-based auth"
```

---

### Task 8: Cards read API

**Files:**
- Create: `backend/cards_router.py`
- Create: `backend/tests/test_cards_router.py`
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `cards.fetch_cards_page`, `cards.get_card`, `cards.search_cards`, `cards.get_card_embedding`, `cards.nearest_neighbors` (Task 2); `query_parser.parse_query`, `query_parser.QueryParseError` (Task 5); `db.get_connection` (Task 1).
- Produces: `cards_router.router` (FastAPI `APIRouter`), routes `GET /api/v1/cards`, `GET /api/v1/cards/search`, `GET /api/v1/cards/{card_id}`, `GET /api/v1/cards/{card_id}/similar`. None require auth.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.cards_router import router


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.cards_router.get_connection", lambda: MagicMock())
    return TestClient(app)


def test_list_cards_returns_page(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.fetch_cards_page", lambda conn, cursor, limit: [{"id": "c1"}])

    response = client.get("/api/v1/cards")

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_search_cards_returns_400_on_bad_query(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/v1/cards/search", params={"q": "xyz:bad"})

    assert response.status_code == 400


def test_search_cards_returns_results_for_valid_query(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.search_cards", lambda conn, sql, params, **k: [{"id": "c1"}])

    response = client.get("/api/v1/cards/search", params={"q": "cmc<=3"})

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_get_card_returns_404_when_missing(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.get_card", lambda conn, card_id: None)

    response = client.get("/api/v1/cards/nope")

    assert response.status_code == 404


def test_similar_cards_returns_404_when_card_has_no_embedding(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.get_card_embedding", lambda conn, card_id: None)

    response = client.get("/api/v1/cards/c1/similar")

    assert response.status_code == 404


def test_similar_cards_returns_neighbors(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.get_card_embedding", lambda conn, card_id: [0.1, 0.2])
    monkeypatch.setattr("backend.cards_router.cards.nearest_neighbors", lambda conn, emb, **k: [{"id": "c2"}])

    response = client.get("/api/v1/cards/c1/similar")

    assert response.status_code == 200
    assert response.json() == [{"id": "c2"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_cards_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.cards_router'`

- [ ] **Step 3: Implement `cards_router.py`**

```python
from fastapi import APIRouter, HTTPException, Query

from backend.pipeline import cards
from backend.pipeline.db import get_connection
from backend.query_parser import QueryParseError, parse_query

router = APIRouter()


@router.get("/api/v1/cards")
def list_cards(cursor: str | None = None, limit: int = 30):
    conn = get_connection()
    try:
        return cards.fetch_cards_page(conn, cursor, limit)
    finally:
        conn.close()


@router.get("/api/v1/cards/search")
def search_cards(q: str = Query(...)):
    try:
        where_sql, params = parse_query(q)
    except QueryParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn = get_connection()
    try:
        return cards.search_cards(conn, where_sql, params)
    finally:
        conn.close()


@router.get("/api/v1/cards/{card_id}")
def get_card(card_id: str):
    conn = get_connection()
    try:
        card = cards.get_card(conn, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Card not found")
        return card
    finally:
        conn.close()


@router.get("/api/v1/cards/{card_id}/similar")
def similar_cards(card_id: str, limit: int = 8):
    conn = get_connection()
    try:
        embedding = cards.get_card_embedding(conn, card_id)
        if embedding is None:
            raise HTTPException(status_code=404, detail="Card not found or has no embedding yet")
        return cards.nearest_neighbors(conn, embedding, limit=limit, exclude_card_id=card_id)
    finally:
        conn.close()
```

Add to `backend/main.py`:

```python
from backend.cards_router import router as cards_router
# ... after app.include_router(auth_router):
app.include_router(cards_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_cards_router.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cards_router.py backend/tests/test_cards_router.py backend/main.py
git commit -m "feat: add cards read API (list, search, get, similar)"
```

---

### Task 9: Saves and views API

**Files:**
- Create: `backend/saves_router.py`
- Create: `backend/views_router.py`
- Create: `backend/tests/test_saves_router.py`
- Create: `backend/tests/test_views_router.py`
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `interactions.add_save`, `interactions.remove_save`, `interactions.list_saves`, `interactions.log_views` (Task 3); `auth.require_user` (Task 7); `db.get_connection` (Task 1).
- Produces: `saves_router.router` with `GET/POST /api/v1/saves`, `DELETE /api/v1/saves/{card_id}` (all require auth); `views_router.router` with `POST /api/v1/views` (requires auth).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_saves_router.py
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.saves_router import router


def _client(monkeypatch, user=None):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.saves_router.get_connection", lambda: MagicMock())
    if user is not None:
        app.dependency_overrides = {}
        from backend.auth import require_user
        app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def test_list_saves_requires_auth():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/v1/saves")
    assert response.status_code == 401


def test_list_saves_returns_saved_cards(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    monkeypatch.setattr("backend.saves_router.interactions.list_saves", lambda conn, uid: [{"id": "c1"}])

    response = client.get("/api/v1/saves")

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_create_save_calls_add_save(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    calls = []
    monkeypatch.setattr("backend.saves_router.interactions.add_save", lambda conn, uid, cid: calls.append((uid, cid)))

    response = client.post("/api/v1/saves", json={"card_id": "c1"})

    assert response.status_code == 200
    assert calls == [(1, "c1")]


def test_delete_save_calls_remove_save(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    calls = []
    monkeypatch.setattr("backend.saves_router.interactions.remove_save", lambda conn, uid, cid: calls.append((uid, cid)))

    response = client.delete("/api/v1/saves/c1")

    assert response.status_code == 200
    assert calls == [(1, "c1")]
```

```python
# backend/tests/test_views_router.py
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.views_router import router


def test_log_views_requires_auth():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/api/v1/views", json={"card_ids": ["c1"]})
    assert response.status_code == 401


def test_log_views_calls_interactions_log_views(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.views_router.get_connection", lambda: MagicMock())
    from backend.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"id": 1}
    client = TestClient(app)
    calls = []
    monkeypatch.setattr("backend.views_router.interactions.log_views", lambda conn, uid, cids: calls.append((uid, cids)))

    response = client.post("/api/v1/views", json={"card_ids": ["c1", "c2"]})

    assert response.status_code == 200
    assert calls == [(1, ["c1", "c2"])]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_saves_router.py backend/tests/test_views_router.py -v`
Expected: FAIL with `ModuleNotFoundError` for both router modules.

- [ ] **Step 3: Implement the routers**

```python
# backend/saves_router.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_user
from backend.pipeline import interactions
from backend.pipeline.db import get_connection

router = APIRouter()


class SaveRequest(BaseModel):
    card_id: str


@router.get("/api/v1/saves")
def list_saves(user=Depends(require_user)):
    conn = get_connection()
    try:
        return interactions.list_saves(conn, user["id"])
    finally:
        conn.close()


@router.post("/api/v1/saves")
def create_save(body: SaveRequest, user=Depends(require_user)):
    conn = get_connection()
    try:
        interactions.add_save(conn, user["id"], body.card_id)
        conn.commit()
        return {"saved": True, "card_id": body.card_id}
    finally:
        conn.close()


@router.delete("/api/v1/saves/{card_id}")
def delete_save(card_id: str, user=Depends(require_user)):
    conn = get_connection()
    try:
        interactions.remove_save(conn, user["id"], card_id)
        conn.commit()
        return {"saved": False, "card_id": card_id}
    finally:
        conn.close()
```

```python
# backend/views_router.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_user
from backend.pipeline import interactions
from backend.pipeline.db import get_connection

router = APIRouter()


class ViewsRequest(BaseModel):
    card_ids: list[str]


@router.post("/api/v1/views")
def log_views(body: ViewsRequest, user=Depends(require_user)):
    conn = get_connection()
    try:
        interactions.log_views(conn, user["id"], body.card_ids)
        conn.commit()
        return {"logged": len(body.card_ids)}
    finally:
        conn.close()
```

Add to `backend/main.py`:

```python
from backend.saves_router import router as saves_router
from backend.views_router import router as views_router
# ...
app.include_router(saves_router)
app.include_router(views_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_saves_router.py backend/tests/test_views_router.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/saves_router.py backend/views_router.py backend/tests/test_saves_router.py backend/tests/test_views_router.py backend/main.py
git commit -m "feat: add saves and views API"
```

---

### Task 10: Recommendations

**Files:**
- Create: `backend/recommendations.py`
- Create: `backend/recommendations_router.py`
- Create: `backend/tests/test_recommendations.py`
- Create: `backend/tests/test_recommendations_router.py`
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `interactions.list_saved_card_embeddings` (Task 3); `cards.nearest_neighbors` (Task 2); `auth.require_user` (Task 7); `db.get_connection` (Task 1).
- Produces: `recommendations.compute_taste_vector(embeddings: list[list[float]]) -> list[float] | None`, `recommendations_router.router` with `GET /api/v1/recommendations` (requires auth).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_recommendations.py
from backend.recommendations import compute_taste_vector


def test_compute_taste_vector_returns_none_for_empty_list():
    assert compute_taste_vector([]) is None


def test_compute_taste_vector_averages_embeddings():
    result = compute_taste_vector([[1.0, 2.0], [3.0, 4.0]])
    assert result == [2.0, 3.0]


def test_compute_taste_vector_single_embedding_returns_itself():
    result = compute_taste_vector([[1.0, 2.0, 3.0]])
    assert result == [1.0, 2.0, 3.0]
```

```python
# backend/tests/test_recommendations_router.py
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.recommendations_router import router


def _client(monkeypatch, user):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.recommendations_router.get_connection", lambda: MagicMock())
    from backend.auth import require_user
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def test_recommendations_requires_auth():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/v1/recommendations")
    assert response.status_code == 401


def test_recommendations_returns_friendly_message_with_zero_saves(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    monkeypatch.setattr("backend.recommendations_router.interactions.list_saved_card_embeddings", lambda conn, uid: [])

    response = client.get("/api/v1/recommendations")

    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert "message" in body


def test_recommendations_returns_nearest_neighbors_of_taste_vector(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    monkeypatch.setattr(
        "backend.recommendations_router.interactions.list_saved_card_embeddings",
        lambda conn, uid: [[1.0, 2.0], [3.0, 4.0]],
    )
    captured = {}

    def fake_nearest_neighbors(conn, embedding, **kwargs):
        captured["embedding"] = embedding
        return [{"id": "c1"}]

    monkeypatch.setattr("backend.recommendations_router.cards.nearest_neighbors", fake_nearest_neighbors)

    response = client.get("/api/v1/recommendations")

    assert response.status_code == 200
    assert response.json() == {"recommendations": [{"id": "c1"}]}
    assert captured["embedding"] == [2.0, 3.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_recommendations.py backend/tests/test_recommendations_router.py -v`
Expected: FAIL with `ModuleNotFoundError` for both modules.

- [ ] **Step 3: Implement**

```python
# backend/recommendations.py
import numpy as np


def compute_taste_vector(embeddings: list[list[float]]) -> list[float] | None:
    if not embeddings:
        return None
    return np.mean(np.array(embeddings), axis=0).tolist()
```

```python
# backend/recommendations_router.py
from fastapi import APIRouter, Depends

from backend.auth import require_user
from backend.pipeline import cards, interactions
from backend.pipeline.db import get_connection
from backend.recommendations import compute_taste_vector

router = APIRouter()


@router.get("/api/v1/recommendations")
def get_recommendations(user=Depends(require_user)):
    conn = get_connection()
    try:
        embeddings = interactions.list_saved_card_embeddings(conn, user["id"])
        taste_vector = compute_taste_vector(embeddings)
        if taste_vector is None:
            return {"recommendations": [], "message": "Save some cards to get recommendations."}
        return {"recommendations": cards.nearest_neighbors(conn, taste_vector, limit=20)}
    finally:
        conn.close()
```

Add to `backend/main.py`:

```python
from backend.recommendations_router import router as recommendations_router
# ...
app.include_router(recommendations_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_recommendations.py backend/tests/test_recommendations_router.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/recommendations.py backend/recommendations_router.py backend/tests/test_recommendations.py backend/tests/test_recommendations_router.py backend/main.py
git commit -m "feat: add content-based recommendations (on-the-fly taste vector + pgvector NN)"
```

---

### Task 11: Natural-language search API

**Files:**
- Create: `backend/search_router.py`
- Create: `backend/tests/test_search_router.py`
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `nl_search.resolve_search_query` (Task 6); `cards.search_cards` (Task 2); `db.get_connection` (Task 1).
- Produces: `search_router.router` with `POST /api/v1/search/natural` (no auth required).

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.search_router import router


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.search_router.get_connection", lambda: MagicMock())
    return TestClient(app)


def test_natural_search_requires_no_auth(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.search_router.resolve_search_query", lambda q: ("cmc <= %s", [3.0]))
    monkeypatch.setattr("backend.search_router.cards.search_cards", lambda conn, sql, params: [{"id": "c1"}])

    response = client.post("/api/v1/search/natural", json={"query": "cheap stuff"})

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_natural_search_passes_query_text_through(monkeypatch):
    client = _client(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        "backend.search_router.resolve_search_query",
        lambda q: captured.setdefault("q", q) or ("name ILIKE %s", ["%x%"]),
    )
    monkeypatch.setattr("backend.search_router.cards.search_cards", lambda conn, sql, params: [])

    client.post("/api/v1/search/natural", json={"query": "low cost commanders"})

    assert captured["q"] == "low cost commanders"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_search_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.search_router'`

- [ ] **Step 3: Implement `search_router.py`**

```python
from fastapi import APIRouter
from pydantic import BaseModel

from backend.nl_search import resolve_search_query
from backend.pipeline import cards
from backend.pipeline.db import get_connection

router = APIRouter()


class NaturalSearchRequest(BaseModel):
    query: str


@router.post("/api/v1/search/natural")
def natural_search(body: NaturalSearchRequest):
    where_sql, params = resolve_search_query(body.query)
    conn = get_connection()
    try:
        return cards.search_cards(conn, where_sql, params)
    finally:
        conn.close()
```

Add to `backend/main.py`:

```python
from backend.search_router import router as search_router
# ...
app.include_router(search_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m pytest backend/tests/test_search_router.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/search_router.py backend/tests/test_search_router.py backend/main.py
git commit -m "feat: add natural-language search API"
```

---

### Task 12: Frontend — card feed (masonry, art_crop, cursor pagination)

**Files:**
- Modify: `src/main.js`
- Modify: `index.html`
- Delete: `music.html`, `src/music.js`, `stats.html`, `src/stats.js`

**Interfaces:**
- Consumes: `GET /api/v1/cards?cursor=&limit=` (Task 8) — returns `[{id, name, artist, image_uris}, ...]`.

This task has no Python test cycle — it's frontend-only. Verification is manual: run the dev server and confirm the feed loads and scrolls.

- [ ] **Step 1: Remove the dead nav destinations**

```bash
git rm music.html src/music.js stats.html src/stats.js
```

- [ ] **Step 2: Update `index.html`**

Remove the `music.html` and `stats.html` sidebar links (their features are cut per the design spec — no MTG equivalent). Update the page title and header text. Add oracle text/mana cost/artist fields to the modal, since the grid now shows only the art crop and the modal is where the full card info lives:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MTG Discovery</title>
    <link rel="preconnect" href="https://fonts.gstatic.com">
    <link href="https://fonts.googleapis.com/css2?family=Uncial+Antiqua&display=swap" rel="stylesheet">

    <link rel="stylesheet" href="src/style.css" />
    <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body>
    <div class="page">
        <aside class="sidebar">
            <ul>
                <li>
                <a href="index.html" class="nav-link">
                    <i data-lucide="home"></i>
                </a>
                </li>
                <li>
                <a href="favorites.html" class="nav-link">
                    <i data-lucide="heart"></i>
                </a>
                </li>
                <li>
                <a href="recommendations.html" class="nav-link">
                    <i data-lucide="sparkles"></i>
                </a>
                </li>
            </ul>
        </aside>

        <main class="gallery-container">
            <header class="page-header">
                <h1 class="page-title">Browse Cards</h1>
                <input type="text" id="search-input" placeholder="Search or describe what you want..." />
            </header>
            <div class="gallery">
                <div class="gutter-sizer"></div>
            </div>
            <div id="scroll-trigger" style="height: 50px;"></div>
        </main>
    </div>

    <div id="image-modal" class="modal">
        <span class="close-btn">&times;</span>
        <img class="modal-content" id="modal-image">
        <div id="modal-details">
            <h2 id="modal-name"></h2>
            <p id="modal-mana-cost"></p>
            <p id="modal-type-line"></p>
            <p id="modal-oracle-text"></p>
            <p id="modal-artist"></p>
            <button id="modal-save-btn">Save</button>
        </div>
    </div>

    <script type="module" src="/src/main.js"></script>
</body>
</html>
```

(The `recommendations.html` link and `#search-input` wiring are completed in Tasks 13-14 — this task adds the markup so those tasks don't also need an `index.html` pass.)

- [ ] **Step 3: Rewrite `src/main.js`'s data-fetching and rendering for cursor pagination and art_crop images**

```javascript
import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';

const API_BASE = 'http://127.0.0.1:8000';

document.addEventListener('DOMContentLoaded', async () => {
  const gallery = document.querySelector('.gallery');
  const scrollTrigger = document.getElementById('scroll-trigger');

  let nextCursor = null;
  let hasMore = true;
  let msnry;
  let isLoading = false;

  async function fetchCardsPage() {
    const params = new URLSearchParams({ limit: '30' });
    if (nextCursor) params.set('cursor', nextCursor);
    try {
      const response = await fetch(`${API_BASE}/api/v1/cards?${params}`);
      if (!response.ok) throw new Error('Network response was not ok');
      return await response.json();
    } catch (error) {
      console.error('Failed to fetch cards:', error);
      gallery.innerHTML = `<p class="error-message">Could not load cards. Please ensure the backend is running.</p>`;
      return [];
    }
  }

  function cardArtUrl(card) {
    return card.image_uris && card.image_uris.art_crop;
  }

  async function loadMoreCards() {
    if (isLoading || !hasMore) return;
    isLoading = true;

    const page = await fetchCardsPage();
    if (page.length === 0) {
      hasMore = false;
      observer.unobserve(scrollTrigger);
      isLoading = false;
      return;
    }
    nextCursor = page[page.length - 1].id;

    if (!msnry) {
      msnry = new Masonry(gallery, {
        itemSelector: '.image-wrapper',
        columnWidth: '.image-wrapper',
        gutter: 15,
      });
    }

    for (const card of page) {
      const artUrl = cardArtUrl(card);
      if (!artUrl) continue;

      const wrapper = document.createElement('div');
      wrapper.classList.add('image-wrapper');
      wrapper.dataset.cardId = card.id;

      const img = document.createElement('img');
      img.src = artUrl;

      const overlay = document.createElement('div');
      overlay.classList.add('overlay');

      const artistLabel = document.createElement('span');
      artistLabel.classList.add('artist-label');
      artistLabel.textContent = card.artist || '';

      wrapper.appendChild(img);
      wrapper.appendChild(overlay);
      wrapper.appendChild(artistLabel);
      gallery.appendChild(wrapper);
      msnry.appended(wrapper);

      await new Promise((resolve) => imagesLoaded(wrapper).on('always', resolve));
      msnry.layout();
    }

    isLoading = false;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) loadMoreCards();
    },
    { rootMargin: '200px' }
  );
  observer.observe(scrollTrigger);
  loadMoreCards();

  window.lucide.createIcons();

  const modal = document.getElementById('image-modal');
  const modalImg = document.getElementById('modal-image');
  const modalName = document.getElementById('modal-name');
  const modalManaCost = document.getElementById('modal-mana-cost');
  const modalTypeLine = document.getElementById('modal-type-line');
  const modalOracleText = document.getElementById('modal-oracle-text');
  const modalArtist = document.getElementById('modal-artist');
  const closeBtn = document.querySelector('.close-btn');

  gallery.addEventListener('click', async (e) => {
    const wrapper = e.target.closest('.image-wrapper');
    if (!wrapper) return;
    const cardId = wrapper.dataset.cardId;
    const img = wrapper.querySelector('img');

    modal.classList.add('modal--active');
    modalImg.src = img.src;
    modalName.textContent = '';
    modalManaCost.textContent = '';
    modalTypeLine.textContent = '';
    modalOracleText.textContent = 'Loading...';
    modalArtist.textContent = '';

    try {
      const response = await fetch(`${API_BASE}/api/v1/cards/${cardId}`);
      const card = await response.json();
      modalName.textContent = card.name;
      modalManaCost.textContent = card.mana_cost || '';
      modalTypeLine.textContent = card.type_line || '';
      modalOracleText.textContent = card.oracle_text || '';
      modalArtist.textContent = card.artist ? `Art by ${card.artist}` : '';
      if (card.image_uris && card.image_uris.normal) {
        modalImg.src = card.image_uris.normal;
      }
    } catch (error) {
      modalOracleText.textContent = 'Could not load card details.';
    }
  });

  function closeModal() {
    modal.classList.remove('modal--active');
  }
  closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });
});
```

Note: the save button (`#modal-save-btn`) and search input wiring are added in Tasks 13-14 — this task's `main.js` is browsable end to end but Save/Search aren't wired yet.

- [ ] **Step 4: Manual verification**

Run: `npm run dev` (from repo root), open the printed local URL in a browser.
Expected: the masonry grid loads card art thumbnails, scrolling near the bottom loads more, clicking a card opens the modal with name/mana cost/type/oracle text/artist and the full card image swapped in. Music and Stats nav links are gone.

- [ ] **Step 5: Commit**

```bash
git add index.html src/main.js
git commit -m "feat: rebuild card feed for cursor-paginated art_crop browsing"
```

---

### Task 13: Frontend — auth integration and My Saves page

**Files:**
- Modify: `src/main.js`
- Modify: `favorites.html` (repurposed as the "My Saves" page — same nav slot/icon, new data source)
- Modify: `src/favorites.js` (rewritten to read from the API instead of `localStorage`)

**Interfaces:**
- Consumes: `GET /auth/login/google` (Task 7, redirect-based — no JSON contract), `POST /api/v1/saves`, `DELETE /api/v1/saves/{card_id}`, `GET /api/v1/saves` (Task 9).

- [ ] **Step 1: Wire the save button in `src/main.js`'s modal**

Add to the modal element-lookup block (alongside `modalArtist`):

```javascript
  const modalSaveBtn = document.getElementById('modal-save-btn');
  let currentModalCardId = null;
```

Inside the `gallery.addEventListener('click', ...)` handler, right after `const cardId = wrapper.dataset.cardId;`:

```javascript
    currentModalCardId = cardId;
    modalSaveBtn.textContent = 'Save';
    modalSaveBtn.classList.remove('saved');
```

Add a new handler, after the modal-close wiring:

```javascript
  modalSaveBtn.addEventListener('click', async () => {
    if (!currentModalCardId) return;
    const isSaved = modalSaveBtn.classList.contains('saved');
    const method = isSaved ? 'DELETE' : 'POST';
    const url = isSaved
      ? `${API_BASE}/api/v1/saves/${currentModalCardId}`
      : `${API_BASE}/api/v1/saves`;

    const response = await fetch(url, {
      method,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: isSaved ? undefined : JSON.stringify({ card_id: currentModalCardId }),
    });

    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }

    modalSaveBtn.textContent = isSaved ? 'Save' : 'Saved';
    modalSaveBtn.classList.toggle('saved', !isSaved);
  });
```

(`credentials: 'include'` is required so the session cookie set by `/auth/callback` is sent with the request — without it, a logged-in user would still get 401s on every save.)

- [ ] **Step 2: Rewrite `favorites.html` as the My Saves page**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>My Saves</title>
  <link rel="stylesheet" href="src/style.css" />
  <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body>
  <div class="page">
    <aside class="sidebar">
      <ul>
        <li><a href="index.html" class="nav-link"><i data-lucide="home"></i></a></li>
        <li><a href="favorites.html" class="nav-link active"><i data-lucide="heart"></i></a></li>
        <li><a href="recommendations.html" class="nav-link"><i data-lucide="sparkles"></i></a></li>
      </ul>
    </aside>

    <main class="gallery-container">
      <header class="page-header">
        <h1 class="page-title">My Saves</h1>
      </header>
      <div class="favorites-gallery" id="favorites-gallery">
        <div class="grid-sizer"></div>
        <div class="gutter-sizer"></div>
      </div>
    </main>
  </div>

  <script src="src/favorites.js" type="module"></script>
</body>
</html>
```

- [ ] **Step 3: Rewrite `src/favorites.js`**

```javascript
import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';

const API_BASE = 'http://127.0.0.1:8000';

document.addEventListener('DOMContentLoaded', async () => {
  const gallery = document.getElementById('favorites-gallery');

  const msnry = new Masonry(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.grid-sizer',
    gutter: '.gutter-sizer',
    percentPosition: true,
  });

  let saved;
  try {
    const response = await fetch(`${API_BASE}/api/v1/saves`, { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }
    saved = await response.json();
  } catch (error) {
    gallery.innerHTML = `<p class="error-message">Could not load your saves.</p>`;
    return;
  }

  for (const card of saved) {
    const artUrl = card.image_uris && card.image_uris.art_crop;
    if (!artUrl) continue;

    const wrapper = document.createElement('div');
    wrapper.classList.add('image-wrapper');

    const img = document.createElement('img');
    img.src = artUrl;

    const overlay = document.createElement('div');
    overlay.classList.add('overlay');

    const removeBtn = document.createElement('button');
    removeBtn.classList.add('remove-btn');
    removeBtn.innerHTML = '<i data-lucide="trash-2"></i>';

    removeBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await fetch(`${API_BASE}/api/v1/saves/${card.id}`, { method: 'DELETE', credentials: 'include' });
      msnry.remove(wrapper);
      msnry.layout();
    });

    wrapper.appendChild(img);
    wrapper.appendChild(overlay);
    wrapper.appendChild(removeBtn);
    gallery.appendChild(wrapper);

    imagesLoaded(wrapper, () => {
      msnry.appended(wrapper);
      msnry.layout();
    });
  }

  window.lucide.createIcons();
});
```

- [ ] **Step 4: Manual verification**

Run: `npm run dev`, open the app.
Expected: clicking Save on a card while logged out redirects to Google login; after logging in and saving a card, it appears on the My Saves page; the trash icon removes it from both the page and (on reload) the backend.

- [ ] **Step 5: Commit**

```bash
git add src/main.js favorites.html src/favorites.js
git commit -m "feat: wire save button to real auth/saves API, rebuild My Saves page"
```

---

### Task 14: Frontend — search bar and For You recommendations

**Files:**
- Modify: `src/main.js`
- Create: `recommendations.html`
- Create: `src/recommendations.js`

**Interfaces:**
- Consumes: `POST /api/v1/search/natural` (Task 11), `GET /api/v1/recommendations` (Task 10).

- [ ] **Step 1: Wire the search input in `src/main.js`**

Add near the top of the `DOMContentLoaded` handler, after the existing `const scrollTrigger = ...` line:

```javascript
  const searchInput = document.getElementById('search-input');
```

Add after the `gallery.addEventListener('click', ...)` block:

```javascript
  let searchDebounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(async () => {
      const query = searchInput.value.trim();
      gallery.innerHTML = '<div class="gutter-sizer"></div>';
      msnry = null;
      if (!query) {
        nextCursor = null;
        hasMore = true;
        loadMoreCards();
        return;
      }

      hasMore = false; // search results aren't paginated in this phase
      try {
        const response = await fetch(`${API_BASE}/api/v1/search/natural`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });
        const results = await response.json();
        msnry = new Masonry(gallery, {
          itemSelector: '.image-wrapper',
          columnWidth: '.image-wrapper',
          gutter: 15,
        });
        for (const card of results) {
          const artUrl = card.image_uris && card.image_uris.art_crop;
          if (!artUrl) continue;
          const wrapper = document.createElement('div');
          wrapper.classList.add('image-wrapper');
          wrapper.dataset.cardId = card.id;
          const img = document.createElement('img');
          img.src = artUrl;
          wrapper.appendChild(img);
          gallery.appendChild(wrapper);
          await new Promise((resolve) => imagesLoaded(wrapper).on('always', resolve));
          msnry.appended(wrapper);
          msnry.layout();
        }
      } catch (error) {
        gallery.innerHTML = '<p class="error-message">Search failed.</p>';
      }
    }, 400);
  });
```

- [ ] **Step 2: Create `recommendations.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>For You</title>
  <link rel="stylesheet" href="src/style.css" />
  <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body>
  <div class="page">
    <aside class="sidebar">
      <ul>
        <li><a href="index.html" class="nav-link"><i data-lucide="home"></i></a></li>
        <li><a href="favorites.html" class="nav-link"><i data-lucide="heart"></i></a></li>
        <li><a href="recommendations.html" class="nav-link active"><i data-lucide="sparkles"></i></a></li>
      </ul>
    </aside>

    <main class="gallery-container">
      <header class="page-header">
        <h1 class="page-title">For You</h1>
      </header>
      <p id="recommendations-message"></p>
      <div class="gallery" id="recommendations-gallery">
        <div class="gutter-sizer"></div>
      </div>
    </main>
  </div>

  <script src="src/recommendations.js" type="module"></script>
</body>
</html>
```

- [ ] **Step 3: Create `src/recommendations.js`**

```javascript
import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';

const API_BASE = 'http://127.0.0.1:8000';

document.addEventListener('DOMContentLoaded', async () => {
  const gallery = document.getElementById('recommendations-gallery');
  const messageEl = document.getElementById('recommendations-message');

  let body;
  try {
    const response = await fetch(`${API_BASE}/api/v1/recommendations`, { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }
    body = await response.json();
  } catch (error) {
    messageEl.textContent = 'Could not load recommendations.';
    return;
  }

  if (body.message) {
    messageEl.textContent = body.message;
  }
  if (!body.recommendations || body.recommendations.length === 0) return;

  const msnry = new Masonry(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.image-wrapper',
    gutter: 15,
  });

  for (const card of body.recommendations) {
    const artUrl = card.image_uris && card.image_uris.art_crop;
    if (!artUrl) continue;
    const wrapper = document.createElement('div');
    wrapper.classList.add('image-wrapper');
    const img = document.createElement('img');
    img.src = artUrl;
    wrapper.appendChild(img);
    gallery.appendChild(wrapper);
    await new Promise((resolve) => imagesLoaded(wrapper).on('always', resolve));
    msnry.appended(wrapper);
    msnry.layout();
  }

  window.lucide.createIcons();
});
```

- [ ] **Step 4: Manual verification**

Run: `npm run dev`.
Expected: typing in the search box on the home page replaces the grid with search results (debounced, ~400ms after typing stops); clearing it restores the normal feed. The "For You" nav item shows saved-card-based recommendations when logged in with saves, or the "save some cards" message otherwise.

- [ ] **Step 5: Commit**

```bash
git add src/main.js recommendations.html src/recommendations.js
git commit -m "feat: add natural-language search bar and For You recommendations page"
```

---

### Task 15: Final cleanup and full verification

**Files:**
- Delete: `backend/database.py`, `backend/audio.py`, `backend/vectordb.py`, `backend/chroma_db/`, `backend/image_sorter/`, `backend/caption.py`, `backend/fantasy_board.db`
- Modify: `backend/__init__.py`
- Modify: `README.md`

**Interfaces:** None — this task removes code, nothing downstream depends on it (everything that imported these was already replaced in Tasks 1-11).

- [ ] **Step 1: Remove the remaining fantasy-art/audio files**

```bash
git rm backend/database.py backend/audio.py backend/vectordb.py backend/caption.py backend/fantasy_board.db
git rm -r backend/chroma_db backend/image_sorter
```

- [ ] **Step 2: Fix `backend/__init__.py`**

It currently does `from backend.database import create_connection, create_table, create_audio_table` — `database.py` is gone. Empty it out (nothing in the new app imports from the `backend` package root):

```python
```

(An empty file — `backend/__init__.py` just needs to exist to mark the package.)

- [ ] **Step 3: Update `README.md`**

Replace the "Core Features/Technical Stack" and "Future Development" sections to describe the MTG app instead of the fantasy-art gallery:

```markdown
# Loreboard

Loreboard is a Magic: The Gathering card discovery app — a Pinterest-style browsing feed for card art, backed by a content-based recommendation system and natural-language search, built on Scryfall's public card database.

## Core Features/Technical Stack

- **Scryfall Bulk Ingestion**: A scheduled pipeline downloads Scryfall's card database (unique artwork) and syncs it into Postgres, with text embeddings generated via the Gemini API for every card.

- **Masonry Card Browsing**: An infinite-scroll, art-focused feed (no login required to browse, per Scryfall's Fan Content Policy) built with vanilla JS and Masonry.

- **Google OAuth Accounts**: Sign in to save cards and build a personalized recommendation profile.

- **Content-Based Recommendations**: A user's saved cards are averaged into a taste vector and matched against all card embeddings via pgvector nearest-neighbor search.

- **Natural-Language Search**: An LLM translates free-text requests ("low cost commanders that draw cards") into structured card search queries.

- **Backend**: FastAPI, Postgres + pgvector.

## Future Development

- Collaborative filtering, once real usage data accumulates (view events are already logged for this).
- Native/PWA mobile client.
- Passive view-weighted signal in the recommender, alongside explicit saves.
```

- [ ] **Step 4: Run the full test suite**

Run: `./.venv/bin/python -m pytest backend/ -q`
Expected: PASS, all tests across `backend/pipeline/tests/` and `backend/tests/` green, no import errors from the deleted files.

- [ ] **Step 5: Manual full-app smoke test**

Run: `npm run dev` (frontend) and, in another terminal, `./.venv/bin/uvicorn backend.main:app --reload` (backend, requires `DATABASE_URL`, `GOOGLE_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `SESSION_SECRET_KEY` set — and at least one `./.venv/bin/python -m backend.pipeline.run` completed against a real Postgres instance so there are cards to browse).
Expected: home page loads and scrolls through card art, search bar returns filtered results, login redirects to Google and back, saving a card works and shows up on My Saves, For You shows recommendations after at least one save.

- [ ] **Step 6: Commit**

```bash
git add -A backend README.md
git commit -m "chore: remove remaining fantasy-art code, update README for MTG pivot"
```
