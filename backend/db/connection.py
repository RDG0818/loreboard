import os

import psycopg2
from pgvector.psycopg2 import register_vector

CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"


def get_connection():
    """Connects to Postgres using DATABASE_URL. Ensures the `vector` extension
    exists before calling register_vector — register_vector looks up the
    `vector` type's OID, which fails on a completely fresh database where the
    extension hasn't been created yet (a migration normally creates it via
    'alembic upgrade head', but that runs independently of get_connection, so
    the bootstrap step must happen here)."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with conn.cursor() as cur:
        cur.execute(CREATE_EXTENSION_SQL)
    conn.commit()
    register_vector(conn)
    return conn


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
