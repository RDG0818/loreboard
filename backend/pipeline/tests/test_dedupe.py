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
