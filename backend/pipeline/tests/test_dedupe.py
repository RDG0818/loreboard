from unittest.mock import MagicMock, patch
from backend.pipeline.types import Candidate
from backend.pipeline import dedupe


def test_hash_file_is_deterministic(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"same-bytes")
    f2 = tmp_path / "b.jpg"
    f2.write_bytes(b"same-bytes")

    assert dedupe.hash_file(str(f)) == dedupe.hash_file(str(f2))


def test_filter_new_excludes_existing_hashes(tmp_path):
    f1 = tmp_path / "new.jpg"
    f1.write_bytes(b"new-content")
    f2 = tmp_path / "old.jpg"
    f2.write_bytes(b"old-content")

    candidates = [
        Candidate(local_path=str(f1), source="reddit", source_title="new", source_url="u1"),
        Candidate(local_path=str(f2), source="reddit", source_title="old", source_url="u2"),
    ]

    old_hash = dedupe.hash_file(str(f2))
    conn = MagicMock()

    with patch("backend.pipeline.dedupe.db.hash_exists", side_effect=lambda c, h: h == old_hash):
        result = dedupe.filter_new(conn, candidates)

    assert len(result) == 1
    assert result[0][0].local_path == str(f1)


def test_filter_new_skips_unreadable_files(tmp_path, capsys):
    f1 = tmp_path / "good.jpg"
    f1.write_bytes(b"good-content")
    missing_path = str(tmp_path / "missing.jpg")

    candidates = [
        Candidate(local_path=missing_path, source="reddit", source_title="bad", source_url="u1"),
        Candidate(local_path=str(f1), source="reddit", source_title="good", source_url="u2"),
    ]

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))

    with patch("backend.pipeline.dedupe.db.hash_exists", return_value=False):
        result = dedupe.filter_new(conn, candidates)

    assert len(result) == 1
    assert result[0][0].local_path == str(f1)
    captured = capsys.readouterr()
    assert "Dedupe: skipping candidate" in captured.out
    assert missing_path in captured.out


def test_filter_new_skips_db_failures(tmp_path, capsys):
    f1 = tmp_path / "a.jpg"
    f1.write_bytes(b"a-content")
    f2 = tmp_path / "b.jpg"
    f2.write_bytes(b"b-content")

    candidates = [
        Candidate(local_path=str(f1), source="reddit", source_title="a", source_url="u1"),
        Candidate(local_path=str(f2), source="reddit", source_title="b", source_url="u2"),
    ]

    conn = MagicMock()

    def hash_exists_side_effect(c, h):
        # First call (for f1) raises exception, second call (for f2) returns False
        if not hasattr(hash_exists_side_effect, 'call_count'):
            hash_exists_side_effect.call_count = 0
        hash_exists_side_effect.call_count += 1
        if hash_exists_side_effect.call_count == 1:
            raise RuntimeError("Database connection lost")
        return False

    with patch("backend.pipeline.dedupe.db.hash_exists", side_effect=hash_exists_side_effect):
        result = dedupe.filter_new(conn, candidates)

    assert len(result) == 1
    assert result[0][0].local_path == str(f2)
    captured = capsys.readouterr()
    assert "Dedupe: skipping candidate" in captured.out
