from unittest.mock import MagicMock, patch
import pytest
from google.genai import errors as genai_errors

from backend.pipeline.config import PipelineConfig
from backend.pipeline.embed import Embedder, build_embedder
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded


def _no_op_limiter():
    return RateLimiter(calls_per_minute=6000, sleep=lambda s: None)


def _embed_response(values):
    response = MagicMock()
    response.embeddings = [MagicMock(values=values)]
    return response


def _api_error(code):
    return genai_errors.APIError(code, {"error": {"message": "boom", "status": "ERROR"}})


def test_embed_text_returns_vector_from_embed_fn():
    embed_fn = MagicMock(return_value=_embed_response([0.1, 0.2, 0.3]))
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    result = embedder.embed_text("some text")

    assert result == [0.1, 0.2, 0.3]
    call_kwargs = embed_fn.call_args.kwargs
    assert call_kwargs["model"] == "gemini-embedding-001"
    assert call_kwargs["contents"] == "some text"
    assert call_kwargs["config"].output_dimensionality == 768


def test_embed_text_raises_daily_quota_exceeded_without_calling_embed_fn():
    embed_fn = MagicMock()
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=0))

    with pytest.raises(DailyQuotaExceeded):
        embedder.embed_text("some text")

    embed_fn.assert_not_called()


def test_embed_text_retries_on_transient_error():
    """Transient error on first call, succeeding on retry — assert result is correct and call_count == 2."""
    embed_fn = MagicMock(
        side_effect=[
            _api_error(503),
            _embed_response([0.1, 0.2, 0.3]),
        ]
    )
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    result = embedder.embed_text("some text")

    assert result == [0.1, 0.2, 0.3]
    assert embed_fn.call_count == 2


def test_embed_text_does_not_retry_on_non_transient_error():
    """Non-transient error on embed_fn — assert it propagates immediately without retry, call_count == 1."""
    embed_fn = MagicMock(side_effect=_api_error(400))
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    with pytest.raises(genai_errors.APIError):
        embedder.embed_text("some text")

    assert embed_fn.call_count == 1


def _config():
    return PipelineConfig(
        gemini_rpm=15,
        gemini_rpd=1200,
    )


def test_build_embedder_uses_externally_supplied_rate_limiter_and_quota(monkeypatch):
    """When a shared rate_limiter/daily_quota are passed in (e.g. so caption
    and embed calls draw from one combined budget), the builder must use
    those instances rather than constructing its own."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    shared_limiter = RateLimiter(calls_per_minute=6000, sleep=lambda s: None)
    shared_quota = DailyQuota(max_calls_per_day=10)

    with patch("backend.pipeline.embed.genai"):
        embedder = build_embedder(_config(), shared_limiter, shared_quota)

    assert embedder._rate_limiter is shared_limiter
    assert embedder._daily_quota is shared_quota


def test_build_embedder_builds_own_rate_limiter_and_quota_when_not_supplied(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")

    with patch("backend.pipeline.embed.genai"):
        embedder = build_embedder(_config())

    assert isinstance(embedder._rate_limiter, RateLimiter)
    assert isinstance(embedder._daily_quota, DailyQuota)
