"""
Non-blocking rate limiter guarding outbound LinkedIn requests.

Deliberately reject-based, not delay-based: this sits in front of a live
HTTP endpoint with a real caller waiting on a response, so making them
wait behind an artificial sleep is poor UX and risks a gateway/client
timeout cutting the connection anyway. Callers that get rejected retry
after the Retry-After window.
"""

import random
import time

from app.config import settings
from app.exceptions import RateLimited


class RateLimiter:
    def __init__(
        self,
        min_interval_seconds: float | None = None,
        jitter_seconds: float | None = None,
    ):
        self._min_interval = (
            min_interval_seconds
            if min_interval_seconds is not None
            else settings.rate_limit_min_interval_seconds
        )
        self._jitter = jitter_seconds if jitter_seconds is not None else settings.rate_limit_jitter_seconds
        self._last_request_at: float | None = None
        # A fresh random threshold is drawn each time a request is allowed
        # through, so the *next* request's required gap is randomized —
        # not the same jitter re-checked repeatedly against one draw.
        self._current_required_gap = self._min_interval

    def check(self) -> None:
        """Call immediately before making an outbound LinkedIn request.
        Raises RateLimited if not enough time has passed since the last
        allowed request. On success, records this request's timestamp and
        draws a new randomized gap for the next one."""
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            if elapsed < self._current_required_gap:
                retry_after = self._current_required_gap - elapsed
                raise RateLimited(
                    "Too many LinkedIn requests in quick succession. "
                    f"Retry after {retry_after:.1f}s.",
                    retry_after_seconds=retry_after,
                )

        self._last_request_at = now
        self._current_required_gap = self._min_interval + random.uniform(0, self._jitter)


# Single shared instance — same reasoning as session_manager: one LinkedIn
# identity, one shared throttle, regardless of how many concurrent callers
# hit /profile.
rate_limiter = RateLimiter()
