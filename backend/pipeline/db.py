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
    embedding vector(768),
    set_type TEXT,
    is_universes_beyond BOOLEAN NOT NULL DEFAULT FALSE
);

-- ADD COLUMN IF NOT EXISTS for databases that already had a `cards` table
-- before these columns existed (CREATE TABLE IF NOT EXISTS above is a no-op
-- on those, since the table already exists).
ALTER TABLE cards ADD COLUMN IF NOT EXISTS set_type TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS is_universes_beyond BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS cards_embedding_hnsw_idx ON cards USING hnsw (embedding vector_cosine_ops);

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
