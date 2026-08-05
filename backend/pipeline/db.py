import os

import psycopg2
from pgvector.psycopg2 import register_vector

from backend.pipeline.rate_limit import with_backoff

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS images (
    hash TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    caption TEXT NOT NULL,
    art_style TEXT,
    fantasy_mood TEXT,
    fantasy_scale TEXT,
    magic_level TEXT,
    tags TEXT,
    dominant_colors TEXT,
    detail_score INTEGER,
    mood_score INTEGER,
    scale_score INTEGER,
    magic_score INTEGER,
    embedding vector(768),
    r2_key TEXT NOT NULL
);
"""

INSERT_SQL = """
INSERT INTO images (
    hash, filename, title, caption, art_style, fantasy_mood, fantasy_scale,
    magic_level, tags, dominant_colors, detail_score, mood_score,
    scale_score, magic_score, embedding, r2_key
) VALUES (
    %(hash)s, %(filename)s, %(title)s, %(caption)s, %(art_style)s,
    %(fantasy_mood)s, %(fantasy_scale)s, %(magic_level)s, %(tags)s,
    %(dominant_colors)s, %(detail_score)s, %(mood_score)s, %(scale_score)s,
    %(magic_score)s, %(embedding)s, %(r2_key)s
)
"""


def get_connection():
    """Connects to Postgres using DATABASE_URL and registers the pgvector type."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    register_vector(conn)
    return conn


def init_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def hash_exists(conn, image_hash: str) -> bool:
    def _query():
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM images WHERE hash = %s", (image_hash,))
            return cur.fetchone() is not None

    return with_backoff(_query, max_retries=3, base_delay=0.5)


def insert_image(conn, record: dict) -> None:
    """Inserts one image row. Does not commit — caller owns the transaction
    boundary so the R2 upload and the DB write can be coordinated."""

    def _insert():
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, record)

    with_backoff(_insert, max_retries=3, base_delay=0.5)
