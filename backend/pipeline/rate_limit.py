import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RateLimiter:
    """Token-bucket-style limiter: blocks the caller until it is safe to
    make another call within `calls_per_minute`."""

    def __init__(
        self,
        calls_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = 60.0 / calls_per_minute
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_call is not None:
            elapsed = now - self._last_call
            remaining = self.min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_call = self._clock()


class DailyQuotaExceeded(Exception):
    """Raised when a daily call budget has been exhausted."""


class DailyQuota:
    """Tracks calls against a daily budget; raises DailyQuotaExceeded once
    the budget is exhausted."""

    def __init__(self, max_calls_per_day: int):
        self.max_calls_per_day = max_calls_per_day
        self._count = 0

    def consume(self) -> None:
        if self._count >= self.max_calls_per_day:
            raise DailyQuotaExceeded(f"Daily quota of {self.max_calls_per_day} calls exhausted")
        self._count += 1


def with_backoff(
    func: Callable[[], T],
    *,
    max_retries: int = 5,
    base_delay: float = 1.0,
    is_retryable: Callable[[Exception], bool] = lambda e: True,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Calls func with exponential backoff on retryable exceptions."""
    attempt = 0
    while True:
        try:
            return func()
        except Exception as e:
            if not is_retryable(e) or attempt >= max_retries:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            sleep(delay)
            attempt += 1
