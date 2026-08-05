import pytest
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded, with_backoff


def test_rate_limiter_sleeps_remaining_interval():
    clock_values = iter([0.0, 0.0, 5.0, 5.0])  # init call, first wait, second wait
    sleeps = []

    limiter = RateLimiter(
        calls_per_minute=60,  # min_interval = 1.0s
        clock=lambda: next(clock_values),
        sleep=lambda s: sleeps.append(s),
    )
    limiter.wait()  # first call: no prior call, no sleep
    limiter.wait()  # second call: elapsed 5.0s >= 1.0s interval... wait, need not sleep

    assert sleeps == []


def test_rate_limiter_sleeps_when_calls_are_too_close():
    clock_values = iter([0.0, 0.0, 0.2, 0.2])
    sleeps = []

    limiter = RateLimiter(
        calls_per_minute=60,  # min_interval = 1.0s
        clock=lambda: next(clock_values),
        sleep=lambda s: sleeps.append(s),
    )
    limiter.wait()
    limiter.wait()

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.8, abs=0.01)


def test_daily_quota_raises_after_max_calls():
    quota = DailyQuota(max_calls_per_day=2)
    quota.consume()
    quota.consume()
    with pytest.raises(DailyQuotaExceeded):
        quota.consume()


def test_with_backoff_retries_then_succeeds():
    attempts = {"count": 0}
    sleeps = []

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("transient")
        return "ok"

    result = with_backoff(flaky, max_retries=5, base_delay=0.01, sleep=lambda s: sleeps.append(s))

    assert result == "ok"
    assert attempts["count"] == 3
    assert len(sleeps) == 2


def test_with_backoff_raises_after_max_retries():
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        with_backoff(always_fails, max_retries=2, base_delay=0.01, sleep=lambda s: None)


def test_with_backoff_does_not_retry_non_retryable():
    calls = {"count": 0}

    def fails_once():
        calls["count"] += 1
        raise ValueError("non-retryable")

    with pytest.raises(ValueError):
        with_backoff(fails_once, max_retries=5, is_retryable=lambda e: False, sleep=lambda s: None)

    assert calls["count"] == 1
