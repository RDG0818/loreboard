import os

import google.generativeai as genai

from backend.pipeline.config import PipelineConfig
from backend.pipeline.gemini_retry import is_transient_gemini_error
from backend.pipeline.rate_limit import DailyQuota, RateLimiter, with_backoff


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
            is_retryable=is_transient_gemini_error,
        )
        return result["embedding"]


def build_embedder(
    config: PipelineConfig,
    rate_limiter: RateLimiter | None = None,
    daily_quota: DailyQuota | None = None,
) -> Embedder:
    """Builds an Embedder. If rate_limiter/daily_quota are not supplied,
    builds standalone ones from config — but callers that also build a
    GeminiAnalyzer should construct one shared RateLimiter/DailyQuota and
    pass them into both builders, since the design budget (gemini_rpm/
    gemini_rpd) is a single ceiling shared across caption and embed calls,
    not one per call site."""
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    if rate_limiter is None:
        rate_limiter = RateLimiter(calls_per_minute=config.gemini_rpm)
    if daily_quota is None:
        daily_quota = DailyQuota(max_calls_per_day=config.gemini_rpd)
    return Embedder(genai.embed_content, rate_limiter, daily_quota)
