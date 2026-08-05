from unittest.mock import MagicMock, patch
from backend.pipeline.caption import AnalysisResult
from backend.pipeline.rate_limit import DailyQuotaExceeded
from backend.pipeline.run import _analysis_to_embedding_text, run


def _analysis():
    return AnalysisResult(
        keep=True,
        rejection_reason=None,
        title="City of Ruins",
        caption="A ruined city under a stormy sky.",
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


def test_analysis_to_embedding_text_includes_key_fields():
    text = _analysis_to_embedding_text(_analysis())
    assert "City of Ruins" in text
    assert "Painterly" in text
    assert "Castle, Ruins" in text
    assert "A ruined city under a stormy sky." in text


def test_run_stops_early_on_daily_quota_but_keeps_already_persisted(tmp_path, monkeypatch):
    from backend.pipeline.types import Candidate

    candidate1 = Candidate(local_path=str(tmp_path / "a.jpg"), source="reddit", source_title="a", source_url="u1")
    candidate2 = Candidate(local_path=str(tmp_path / "b.jpg"), source="reddit", source_title="b", source_url="u2")
    for c in (candidate1, candidate2):
        with open(c.local_path, "wb") as f:
            f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=10))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.build_reddit_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.scrape_reddit", lambda cfg, client, dest: [candidate1, candidate2])
    monkeypatch.setattr("backend.pipeline.run.get_access_token", lambda cid, secret: "tok")
    monkeypatch.setattr("backend.pipeline.run.scrape_deviantart", lambda cfg, token, dest: [])
    monkeypatch.setattr("backend.pipeline.run.dedupe.filter_new", lambda conn, cands: [(c, f"hash-{i}") for i, c in enumerate(cands)])
    monkeypatch.setattr("backend.pipeline.run.load_clip_model", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.passes_heuristics", lambda path: True)
    monkeypatch.setattr("backend.pipeline.run.passes_content_gate", lambda model, path, threshold: True)

    persisted = []
    monkeypatch.setattr("backend.pipeline.run.persist_image", lambda *a, **k: persisted.append(a))

    analyzer = MagicMock()
    analyzer.analyze_image.side_effect = [_analysis(), DailyQuotaExceeded("quota gone")]
    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", lambda cfg: analyzer)

    embedder = MagicMock()
    embedder.embed_text.return_value = [0.1, 0.2]
    monkeypatch.setattr("backend.pipeline.run.build_embedder", lambda cfg: embedder)

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    assert len(persisted) == 1  # second image stopped the loop before persisting
