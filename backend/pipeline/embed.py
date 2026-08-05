import os

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from backend.pipeline.config import PipelineConfig
from backend.pipeline.rate_limit import DailyQuota, RateLimiter, with_backoff


def _is_transient(e: Exception) -> bool:
    """Filter to transient/retryable Gemini API errors only."""
    return isinstance(
        e,
        (
            google_exceptions.ResourceExhausted,
            google_exceptions.ServiceUnavailable,
            google_exceptions.DeadlineExceeded,
        ),
    )


class Embedder:
    def __init__(self, embed_fn, rate_limiter: RateLimiter, daily_quota: DailyQuota):
        self._embed_fn = embed_fn
        self._rate_limiter = rate_limiter
        self._daily_quota = daily_quota

    def embed_text(self, text: str) -> list[float]:
        self._daily_quota.consume()
        self._rate_limiter.wait()
        result = with_backoff(
            lambda: self._embed_fn(model="models/text-embedding-004", content=text),
            is_retryable=_is_transient,
        )
        return result["embedding"]


def build_embedder(config: PipelineConfig) -> Embedder:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    rate_limiter = RateLimiter(calls_per_minute=config.gemini_rpm)
    daily_quota = DailyQuota(max_calls_per_day=config.gemini_rpd)
    return Embedder(genai.embed_content, rate_limiter, daily_quota)
