from backend.ingest.config import load_config, PipelineConfig


def test_load_config_returns_defaults():
    cfg = load_config()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.gemini_rpm == 15
    assert cfg.gemini_rpd == 1200
