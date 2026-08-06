import dataclasses
import os


@dataclasses.dataclass
class PipelineConfig:
    artstation_queries: list[str]
    deviantart_tags: list[str]
    images_per_run: int
    clip_confidence_threshold: float
    gemini_rpm: int
    gemini_rpd: int


DEFAULT_CONFIG = PipelineConfig(
    artstation_queries=["fantasy art", "concept art", "digital painting"],
    deviantart_tags=["fantasyart", "digitalpainting", "conceptart"],
    images_per_run=200,
    clip_confidence_threshold=0.26,
    gemini_rpm=15,
    gemini_rpd=1200,  # capped comfortably under the 1500/day free-tier limit
)


def load_config() -> PipelineConfig:
    """Loads PipelineConfig from DEFAULT_CONFIG with env var overrides."""
    cfg = DEFAULT_CONFIG
    override = os.getenv("PIPELINE_IMAGES_PER_RUN")
    if override:
        cfg = dataclasses.replace(cfg, images_per_run=int(override))
    return cfg
