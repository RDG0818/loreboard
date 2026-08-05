from unittest.mock import MagicMock
import pytest
from google.api_core import exceptions as google_exceptions

from backend.pipeline.embed import Embedder
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded


def _no_op_limiter():
    return RateLimiter(calls_per_minute=6000, sleep=lambda s: None)


def test_embed_text_returns_vector_from_embed_fn():
    embed_fn = MagicMock(return_value={"embedding": [0.1, 0.2, 0.3]})
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    result = embedder.embed_text("some text")

    assert result == [0.1, 0.2, 0.3]
    embed_fn.assert_called_once_with(model="models/text-embedding-004", content="some text")


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
            google_exceptions.ServiceUnavailable("Service temporarily unavailable"),
            {"embedding": [0.1, 0.2, 0.3]},
        ]
    )
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    result = embedder.embed_text("some text")

    assert result == [0.1, 0.2, 0.3]
    assert embed_fn.call_count == 2


def test_embed_text_does_not_retry_on_non_transient_error():
    """Non-transient error on embed_fn — assert it propagates immediately without retry, call_count == 1."""
    embed_fn = MagicMock(
        side_effect=google_exceptions.InvalidArgument("Invalid model")
    )
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    with pytest.raises(google_exceptions.InvalidArgument):
        embedder.embed_text("some text")

    assert embed_fn.call_count == 1
