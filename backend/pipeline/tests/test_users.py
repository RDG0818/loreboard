from unittest.mock import MagicMock
from backend.pipeline import users


def test_get_or_create_user_returns_existing_row():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"id": 1, "google_sub": "sub1", "email": "a@b.com"}

    result = users.get_or_create_user(conn, "sub1", "a@b.com")

    assert result == {"id": 1, "google_sub": "sub1", "email": "a@b.com"}
    assert cursor.execute.call_count == 1
    sql = cursor.execute.call_args[0][0]
    assert "ON CONFLICT" in sql
    assert "EXCLUDED.email" in sql


def test_get_or_create_user_inserts_when_not_found():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"id": 2, "google_sub": "sub2", "email": "c@d.com"}

    result = users.get_or_create_user(conn, "sub2", "c@d.com")

    assert result == {"id": 2, "google_sub": "sub2", "email": "c@d.com"}
    assert cursor.execute.call_count == 1
    sql = cursor.execute.call_args[0][0]
    assert "ON CONFLICT" in sql
    assert "EXCLUDED.email" in sql


def test_get_user_by_id_returns_none_when_missing():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    assert users.get_user_by_id(conn, 999) is None
