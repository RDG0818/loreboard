import gzip
import json

import requests
from dotenv import load_dotenv

load_dotenv()

from backend.db import cards
from backend.db import connection as db
from backend.ingest.config import load_config
from backend.ingest.embed import build_embedder
from backend.ingest.rate_limit import DailyQuota, DailyQuotaExceeded, RateLimiter

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
