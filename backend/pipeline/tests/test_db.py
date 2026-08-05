from unittest.mock import MagicMock
import psycopg2
from backend.pipeline import db


def test_hash_exists_true_when_row_found():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)

    assert db.hash_exists(conn, "abc123") is True
    cursor.execute.assert_called_once_with("SELECT 1 FROM images WHERE hash = %s", ("abc123",))


def test_hash_exists_false_when_no_row():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    assert db.hash_exists(conn, "abc123") is False


def test_insert_image_executes_without_committing():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    record = {
        "hash": "h1",
        "filename": "f.jpg",
        "title": "T",
        "caption": "C",
        "art_style": "Painterly",
        "fantasy_mood": "Dark Fantasy",
        "fantasy_scale": "Large Scale",
        "magic_level": "High Magic",
        "tags": "Dragon,Castle",
        "dominant_colors": "Crimson Red",
        "detail_score": 8,
        "mood_score": 3,
        "scale_score": 9,
        "magic_score": 9,
        "embedding": [0.1, 0.2, 0.3],
        "r2_key": "images/h1.jpg",
    }

    db.insert_image(conn, record)

    cursor.execute.assert_called_once()
    conn.commit.assert_not_called()


def test_hash_exists_does_not_retry_on_integrity_error():
    """Non-transient errors should raise immediately without retries."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = psycopg2.IntegrityError("duplicate key")

    try:
        db.hash_exists(conn, "abc123")
        assert False, "Expected IntegrityError to be raised"
    except psycopg2.IntegrityError:
        pass

    # Should only call execute once (no retries)
    cursor.execute.assert_called_once()


def test_insert_image_does_not_retry_on_integrity_error():
    """Non-transient errors should raise immediately without retries."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = psycopg2.IntegrityError("duplicate key")
    record = {
        "hash": "h1",
        "filename": "f.jpg",
        "title": "T",
        "caption": "C",
        "art_style": "Painterly",
        "fantasy_mood": "Dark Fantasy",
        "fantasy_scale": "Large Scale",
        "magic_level": "High Magic",
        "tags": "Dragon,Castle",
        "dominant_colors": "Crimson Red",
        "detail_score": 8,
        "mood_score": 3,
        "scale_score": 9,
        "magic_score": 9,
        "embedding": [0.1, 0.2, 0.3],
        "r2_key": "images/h1.jpg",
    }

    try:
        db.insert_image(conn, record)
        assert False, "Expected IntegrityError to be raised"
    except psycopg2.IntegrityError:
        pass

    # Should only call execute once (no retries)
    cursor.execute.assert_called_once()


def test_hash_exists_retries_on_operational_error():
    """Transient OperationalError should be retried and eventually succeed."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    # Fail twice with OperationalError, then succeed on third attempt
    cursor.execute.side_effect = [
        psycopg2.OperationalError("server closed the connection unexpectedly"),
        psycopg2.OperationalError("connection lost"),
        None,  # Success on third attempt
    ]
    cursor.fetchone.return_value = (1,)

    result = db.hash_exists(conn, "abc123")

    assert result is True
    # Should call execute 3 times (2 failures + 1 success)
    assert cursor.execute.call_count == 3


def test_insert_image_retries_on_operational_error():
    """Transient OperationalError should be retried and eventually succeed."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    # Fail twice with OperationalError, then succeed on third attempt
    cursor.execute.side_effect = [
        psycopg2.OperationalError("server closed the connection unexpectedly"),
        psycopg2.OperationalError("connection lost"),
        None,  # Success on third attempt
    ]

    record = {
        "hash": "h1",
        "filename": "f.jpg",
        "title": "T",
        "caption": "C",
        "art_style": "Painterly",
        "fantasy_mood": "Dark Fantasy",
        "fantasy_scale": "Large Scale",
        "magic_level": "High Magic",
        "tags": "Dragon,Castle",
        "dominant_colors": "Crimson Red",
        "detail_score": 8,
        "mood_score": 3,
        "scale_score": 9,
        "magic_score": 9,
        "embedding": [0.1, 0.2, 0.3],
        "r2_key": "images/h1.jpg",
    }

    db.insert_image(conn, record)

    # Should call execute 3 times (2 failures + 1 success)
    assert cursor.execute.call_count == 3
    conn.commit.assert_not_called()
