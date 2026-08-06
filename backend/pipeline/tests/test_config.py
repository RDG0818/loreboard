import os
from backend.pipeline.config import load_config, PipelineConfig


def test_load_config_returns_defaults(monkeypatch):
    monkeypatch.delenv("PIPELINE_IMAGES_PER_RUN", raising=False)
    cfg = load_config()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.images_per_run == 200
    assert "fantasy art" in cfg.artstation_queries
    assert cfg.gemini_rpm == 15
    assert cfg.gemini_rpd == 1200


def test_load_config_honors_images_per_run_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_IMAGES_PER_RUN", "50")
    cfg = load_config()
    assert cfg.images_per_run == 50
