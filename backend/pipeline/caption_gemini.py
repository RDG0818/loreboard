import os

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from PIL import Image

from backend.pipeline.caption import ANALYSIS_PROMPT, AnalysisResult, MalformedAnalysisError, parse_analysis_json
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
                is_retryable=_is_transient,
            )
            try:
                return parse_analysis_json(response.text)
            except MalformedAnalysisError as e:
                last_error = e
                continue

        raise last_error


def build_gemini_analyzer(config: PipelineConfig) -> GeminiAnalyzer:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    rate_limiter = RateLimiter(calls_per_minute=config.gemini_rpm)
    daily_quota = DailyQuota(max_calls_per_day=config.gemini_rpd)
    return GeminiAnalyzer(model, rate_limiter, daily_quota)
