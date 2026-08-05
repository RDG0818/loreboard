from unittest.mock import MagicMock
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
