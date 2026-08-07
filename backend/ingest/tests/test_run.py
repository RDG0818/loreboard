from unittest.mock import MagicMock
from backend.ingest import run
from backend.ingest.rate_limit import DailyQuotaExceeded


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
