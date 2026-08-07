from unittest.mock import MagicMock
from backend.db import interactions


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
