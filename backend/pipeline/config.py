import dataclasses
import os


@dataclasses.dataclass
class PipelineConfig:
    gemini_rpm: int
    gemini_rpd: int


DEFAULT_CONFIG = PipelineConfig(
    gemini_rpm=15,
    gemini_rpd=1200,  # capped comfortably under the 1500/day free-tier limit
)


def load_config() -> PipelineConfig:
    return DEFAULT_CONFIG
