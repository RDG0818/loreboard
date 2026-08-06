import os

import google.generativeai as genai
from PIL import Image

from backend.pipeline.caption import ANALYSIS_PROMPT, AnalysisResult, MalformedAnalysisError, parse_analysis_json
from backend.pipeline.config import PipelineConfig
from backend.pipeline.gemini_retry import is_transient_gemini_error
from backend.pipeline.rate_limit import DailyQuota, RateLimiter, with_backoff


class GeminiAnalyzer:
    def __init__(
        self,
        model,
        rate_limiter: RateLimiter,
        daily_quota: DailyQuota,
        max_parse_retries: int = 2,
    ):
        self._model = model
        self._rate_limiter = rate_limiter
        self._daily_quota = daily_quota
        self._max_parse_retries = max_parse_retries

    def analyze_image(self, image_path: str) -> AnalysisResult:
        self._daily_quota.consume()  # raises DailyQuotaExceeded before any call is made

        img = Image.open(image_path)
        last_error: Exception | None = None

        for _ in range(self._max_parse_retries + 1):
            self._rate_limiter.wait()
            response = with_backoff(
                lambda: self._model.generate_content(
                    [ANALYSIS_PROMPT, img],
                    generation_config={"response_mime_type": "application/json"},
                ),
                is_retryable=is_transient_gemini_error,
            )
            try:
                return parse_analysis_json(response.text)
            except MalformedAnalysisError as e:
                last_error = e
                continue

        raise last_error


def build_gemini_analyzer(
    config: PipelineConfig,
    rate_limiter: RateLimiter | None = None,
    daily_quota: DailyQuota | None = None,
) -> GeminiAnalyzer:
    """Builds a GeminiAnalyzer. If rate_limiter/daily_quota are not supplied,
    builds standalone ones from config — but callers that also build an
    Embedder should construct one shared RateLimiter/DailyQuota and pass them
    into both builders, since the design budget (gemini_rpm/gemini_rpd) is a
    single ceiling shared across caption and embed calls, not one per call
    site."""
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    if rate_limiter is None:
        rate_limiter = RateLimiter(calls_per_minute=config.gemini_rpm)
    if daily_quota is None:
        daily_quota = DailyQuota(max_calls_per_day=config.gemini_rpd)
    return GeminiAnalyzer(model, rate_limiter, daily_quota)
