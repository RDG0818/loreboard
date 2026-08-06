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

    candidate1 = Candidate(local_path=str(tmp_path / "a.jpg"), source="artstation", source_title="a", source_url="u1")
    candidate2 = Candidate(local_path=str(tmp_path / "b.jpg"), source="artstation", source_title="b", source_url="u2")
    for c in (candidate1, candidate2):
        with open(c.local_path, "wb") as f:
            f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=10))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.scrape_artstation", lambda cfg, dest: [candidate1, candidate2])
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
    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", lambda cfg, *a, **k: analyzer)

    embedder = MagicMock()
    embedder.embed_text.return_value = [0.1, 0.2]
    monkeypatch.setattr("backend.pipeline.run.build_embedder", lambda cfg, *a, **k: embedder)

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    assert len(persisted) == 1  # second image stopped the loop before persisting


def test_run_truncates_combined_candidates_to_images_per_run(tmp_path, monkeypatch):
    from backend.pipeline.types import Candidate

    artstation_candidates = [
        Candidate(local_path=str(tmp_path / f"r{i}.jpg"), source="artstation", source_title=f"r{i}", source_url=f"ru{i}")
        for i in range(3)
    ]
    deviantart_candidates = [
        Candidate(local_path=str(tmp_path / f"d{i}.jpg"), source="deviantart", source_title=f"d{i}", source_url=f"du{i}")
        for i in range(3)
    ]
    for c in artstation_candidates + deviantart_candidates:
        with open(c.local_path, "wb") as f:
            f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=4))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.scrape_artstation", lambda cfg, dest: artstation_candidates)
    monkeypatch.setattr("backend.pipeline.run.get_access_token", lambda cid, secret: "tok")
    monkeypatch.setattr("backend.pipeline.run.scrape_deviantart", lambda cfg, token, dest: deviantart_candidates)

    filter_new_calls = []

    def fake_filter_new(conn, cands):
        filter_new_calls.append(cands)
        return []

    monkeypatch.setattr("backend.pipeline.run.dedupe.filter_new", fake_filter_new)
    monkeypatch.setattr("backend.pipeline.run.load_clip_model", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", lambda cfg, *a, **k: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.build_embedder", lambda cfg, *a, **k: MagicMock())

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    assert len(filter_new_calls) == 1
    assert len(filter_new_calls[0]) == 4


def test_run_skips_candidate_on_generic_exception_and_continues(tmp_path, monkeypatch):
    from backend.pipeline.types import Candidate

    candidate1 = Candidate(local_path=str(tmp_path / "a.jpg"), source="artstation", source_title="a", source_url="u1")
    candidate2 = Candidate(local_path=str(tmp_path / "b.jpg"), source="artstation", source_title="b", source_url="u2")
    for c in (candidate1, candidate2):
        with open(c.local_path, "wb") as f:
            f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=10))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.scrape_artstation", lambda cfg, dest: [candidate1, candidate2])
    monkeypatch.setattr("backend.pipeline.run.get_access_token", lambda cid, secret: "tok")
    monkeypatch.setattr("backend.pipeline.run.scrape_deviantart", lambda cfg, token, dest: [])
    monkeypatch.setattr(
        "backend.pipeline.run.dedupe.filter_new",
        lambda conn, cands: [(c, f"hash-{i}") for i, c in enumerate(cands)],
    )
    monkeypatch.setattr("backend.pipeline.run.load_clip_model", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.passes_heuristics", lambda path: True)
    monkeypatch.setattr("backend.pipeline.run.passes_content_gate", lambda model, path, threshold: True)

    persisted = []
    monkeypatch.setattr("backend.pipeline.run.persist_image", lambda *a, **k: persisted.append(a))

    analyzer = MagicMock()
    analyzer.analyze_image.side_effect = [RuntimeError("boom"), _analysis()]
    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", lambda cfg, *a, **k: analyzer)

    embedder = MagicMock()
    embedder.embed_text.return_value = [0.1, 0.2]
    monkeypatch.setattr("backend.pipeline.run.build_embedder", lambda cfg, *a, **k: embedder)

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    # first candidate raised and was skipped; second candidate still processed
    assert len(persisted) == 1
    assert analyzer.analyze_image.call_count == 2


def test_run_processes_other_source_when_one_source_scrape_fails(tmp_path, monkeypatch):
    from backend.pipeline.types import Candidate

    deviantart_candidate = Candidate(
        local_path=str(tmp_path / "d.jpg"), source="deviantart", source_title="d", source_url="du1"
    )
    with open(deviantart_candidate.local_path, "wb") as f:
        f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=10))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())

    def failing_scrape_artstation(cfg, dest):
        raise RuntimeError("artstation search failed")

    monkeypatch.setattr("backend.pipeline.run.scrape_artstation", failing_scrape_artstation)
    monkeypatch.setattr("backend.pipeline.run.get_access_token", lambda cid, secret: "tok")
    monkeypatch.setattr("backend.pipeline.run.scrape_deviantart", lambda cfg, token, dest: [deviantart_candidate])
    monkeypatch.setattr(
        "backend.pipeline.run.dedupe.filter_new",
        lambda conn, cands: [(c, f"hash-{i}") for i, c in enumerate(cands)],
    )
    monkeypatch.setattr("backend.pipeline.run.load_clip_model", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.passes_heuristics", lambda path: True)
    monkeypatch.setattr("backend.pipeline.run.passes_content_gate", lambda model, path, threshold: True)

    persisted = []
    monkeypatch.setattr("backend.pipeline.run.persist_image", lambda *a, **k: persisted.append(a))

    analyzer = MagicMock()
    analyzer.analyze_image.return_value = _analysis()
    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", lambda cfg, *a, **k: analyzer)

    embedder = MagicMock()
    embedder.embed_text.return_value = [0.1, 0.2]
    monkeypatch.setattr("backend.pipeline.run.build_embedder", lambda cfg, *a, **k: embedder)

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    # ArtStation's scrape raised entirely, but the DeviantArt candidate was
    # still processed and persisted.
    assert len(persisted) == 1


def test_run_shares_one_rate_limiter_and_daily_quota_between_analyzer_and_embedder(tmp_path, monkeypatch):
    """The design budget (gemini_rpm/gemini_rpd) is one ceiling shared across
    Gemini caption and embed calls — run() must construct a single
    RateLimiter/DailyQuota pair and pass the *same* instances into both
    build_gemini_analyzer and build_embedder, not build one pair per call."""
    from backend.pipeline.types import Candidate

    candidate = Candidate(local_path=str(tmp_path / "a.jpg"), source="artstation", source_title="a", source_url="u1")
    with open(candidate.local_path, "wb") as f:
        f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=10, gemini_rpm=15, gemini_rpd=1200))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.scrape_artstation", lambda cfg, dest: [candidate])
    monkeypatch.setattr("backend.pipeline.run.get_access_token", lambda cid, secret: "tok")
    monkeypatch.setattr("backend.pipeline.run.scrape_deviantart", lambda cfg, token, dest: [])
    monkeypatch.setattr(
        "backend.pipeline.run.dedupe.filter_new",
        lambda conn, cands: [(c, f"hash-{i}") for i, c in enumerate(cands)],
    )
    monkeypatch.setattr("backend.pipeline.run.load_clip_model", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.passes_heuristics", lambda path: True)
    monkeypatch.setattr("backend.pipeline.run.passes_content_gate", lambda model, path, threshold: True)
    monkeypatch.setattr("backend.pipeline.run.persist_image", lambda *a, **k: None)

    analyzer_calls = []
    embedder_calls = []

    def fake_build_analyzer(cfg, rate_limiter=None, daily_quota=None):
        analyzer_calls.append((rate_limiter, daily_quota))
        analyzer = MagicMock()
        analyzer.analyze_image.return_value = _analysis()
        return analyzer

    def fake_build_embedder(cfg, rate_limiter=None, daily_quota=None):
        embedder_calls.append((rate_limiter, daily_quota))
        embedder = MagicMock()
        embedder.embed_text.return_value = [0.1, 0.2]
        return embedder

    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", fake_build_analyzer)
    monkeypatch.setattr("backend.pipeline.run.build_embedder", fake_build_embedder)

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    assert len(analyzer_calls) == 1
    assert len(embedder_calls) == 1
    analyzer_limiter, analyzer_quota = analyzer_calls[0]
    embedder_limiter, embedder_quota = embedder_calls[0]
    assert analyzer_limiter is not None and analyzer_quota is not None
    assert analyzer_limiter is embedder_limiter
    assert analyzer_quota is embedder_quota
