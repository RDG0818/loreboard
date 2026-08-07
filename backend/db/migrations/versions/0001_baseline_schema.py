"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-08-07

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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

-- gin_trgm_ops speeds up the ILIKE '%word%' scans in query_parser.py (name/
-- oracle_text/type_line lookups) — a plain B-tree can't help a leading-
-- wildcard match, trigram indexing can.
CREATE INDEX IF NOT EXISTS cards_name_trgm_idx ON cards USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cards_oracle_text_trgm_idx ON cards USING gin (oracle_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cards_type_line_trgm_idx ON cards USING gin (type_line gin_trgm_ops);

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


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cards_type_line_trgm_idx;")
    op.execute("DROP INDEX IF EXISTS cards_oracle_text_trgm_idx;")
    op.execute("DROP INDEX IF EXISTS cards_name_trgm_idx;")
    op.execute("DROP INDEX IF EXISTS cards_embedding_hnsw_idx;")
    op.execute("DROP TABLE IF EXISTS views;")
    op.execute("DROP TABLE IF EXISTS saves;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TABLE IF EXISTS cards;")
