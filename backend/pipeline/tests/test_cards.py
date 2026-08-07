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


def test_fetch_cards_page_orders_by_id_without_seed():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cards.fetch_cards_page(conn, cursor=None, limit=30)
    sql, params = cursor.execute.call_args[0]
    assert "ORDER BY id LIMIT" in sql
    assert "md5" not in sql
    assert params["seed"] is None


def test_fetch_cards_page_orders_by_seeded_hash_first_page():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cards.fetch_cards_page(conn, cursor=None, limit=30, seed="abc")
    sql, params = cursor.execute.call_args[0]
    assert "ORDER BY md5(id || %(seed)s), id LIMIT" in sql
    assert "WHERE" not in sql
    assert params["seed"] == "abc"


def test_fetch_cards_page_seeded_continuation_recomputes_hash_for_cursor():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cards.fetch_cards_page(conn, cursor="c1", limit=30, seed="abc")
    sql, params = cursor.execute.call_args[0]
    assert "WHERE (md5(id || %(seed)s), id) > (md5(%(cursor)s || %(seed)s), %(cursor)s)" in sql
    assert "ORDER BY md5(id || %(seed)s), id LIMIT" in sql
    assert params["cursor"] == "c1"
    assert params["seed"] == "abc"
