from unittest.mock import MagicMock, patch
from backend.pipeline.caption import AnalysisResult
from backend.pipeline.persist import persist_image


def _analysis():
    return AnalysisResult(
        keep=True,
        rejection_reason=None,
        title="City of Ruins",
        caption="A caption.",
        art_style="Painterly",
        fantasy_mood="Dark Fantasy",
        fantasy_scale="Large Scale",
        magic_level="High Magic",
        tags=["Castle", "Ruins"],
        dominant_colors=["Crimson Red"],
        detail_score=8,
        mood_score=2,
        scale_score=9,
        magic_score=7,
    )


def test_persist_image_uploads_then_inserts_then_commits():
    conn = MagicMock()
    r2_client = MagicMock()
    calls = []

    with patch("backend.pipeline.persist.storage.upload_image", side_effect=lambda *a, **k: calls.append("upload")) as upload_mock, \
         patch("backend.pipeline.persist.db.insert_image", side_effect=lambda *a, **k: calls.append("insert")) as insert_mock:
        persist_image(conn, r2_client, "/tmp/f.jpg", "hash123", "f.jpg", _analysis(), [0.1, 0.2])

    upload_mock.assert_called_once_with(r2_client, "/tmp/f.jpg", "images/f.jpg")
    insert_mock.assert_called_once()
    conn.commit.assert_called_once()
    assert calls == ["upload", "insert"]  # upload must happen before the DB write


def test_persist_image_does_not_commit_if_upload_fails():
    conn = MagicMock()
    r2_client = MagicMock()

    with patch("backend.pipeline.persist.storage.upload_image", side_effect=RuntimeError("upload failed")):
        try:
            persist_image(conn, r2_client, "/tmp/f.jpg", "hash123", "f.jpg", _analysis(), [0.1, 0.2])
        except RuntimeError:
            pass

    conn.commit.assert_not_called()
