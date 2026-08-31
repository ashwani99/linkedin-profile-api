"""
Tests control time.monotonic() directly via monkeypatch instead of real
time.sleep() calls — makes these deterministic and instant, rather than
flaky/slow tests that depend on actual wall-clock timing.
"""

import pytest

from app.core.rate_limiter import RateLimiter
from app.exceptions import RateLimited


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr("app.core.rate_limiter.time.monotonic", fake.time)
    return fake


def test_first_call_always_allowed(clock):
    limiter = RateLimiter(min_interval_seconds=5.0, jitter_seconds=0.0)
    limiter.check()  # should not raise


def test_second_call_too_soon_is_rejected(clock):
    limiter = RateLimiter(min_interval_seconds=5.0, jitter_seconds=0.0)
    limiter.check()
    clock.advance(1.0)  # only 1s passed, need 5s
    with pytest.raises(RateLimited):
        limiter.check()


def test_call_after_interval_elapses_is_allowed(clock):
    limiter = RateLimiter(min_interval_seconds=5.0, jitter_seconds=0.0)
    limiter.check()
    clock.advance(5.1)
    limiter.check()  # should not raise


def test_retry_after_reflects_remaining_wait(clock):
    limiter = RateLimiter(min_interval_seconds=5.0, jitter_seconds=0.0)
    limiter.check()
    clock.advance(2.0)  # 3s remaining
    with pytest.raises(RateLimited) as exc_info:
        limiter.check()
    # Retry-After header is a string of an int number of seconds, rounded up
    retry_after = int(exc_info.value.headers["Retry-After"])
    assert retry_after in (3, 4)  # ~3s remaining, +1s ceiling buffer in RateLimited.__init__


def test_jitter_randomizes_next_required_gap(clock, monkeypatch):
    """With jitter, the gap required for the NEXT request should vary
    across accepted calls — not be identical every time."""
    monkeypatch.setattr("app.core.rate_limiter.random.uniform", lambda a, b: 1.5)
    limiter = RateLimiter(min_interval_seconds=5.0, jitter_seconds=3.0)
    limiter.check()
    # required gap should now be min_interval + jitter draw = 5.0 + 1.5 = 6.5
    assert limiter._current_required_gap == pytest.approx(6.5)


def test_rejected_calls_do_not_reset_the_clock(clock):
    """A rejected check() must not count as 'a request happened' — only
    an accepted one should update _last_request_at, otherwise a burst of
    rejected calls would keep pushing the window forward indefinitely."""
    limiter = RateLimiter(min_interval_seconds=5.0, jitter_seconds=0.0)
    limiter.check()
    clock.advance(1.0)
    with pytest.raises(RateLimited):
        limiter.check()
    clock.advance(1.0)  # total 2s since the real allowed call — still < 5s
    with pytest.raises(RateLimited):
        limiter.check()
    clock.advance(3.1)  # total 5.1s since the real allowed call — now OK
    limiter.check()  # should not raise
