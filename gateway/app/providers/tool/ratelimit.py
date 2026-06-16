"""Per-provider fixed-window rate limiter for tool egress (ADR 0014).

Self-contained, in-memory, per-provider. NOT the gateway's global
``rate_limits`` (whose enforcement middleware is unwired). The clock is
injectable so tests are deterministic without sleeping."""

from __future__ import annotations

import time
from collections.abc import Callable

_WINDOW_SECONDS = 60.0


class RateLimited(Exception):
    """Raised when a provider exceeds its per-minute request budget."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"rate limit exceeded for tool provider {provider!r}")
        self.provider = provider


class FixedWindowRateLimiter:
    """Fixed 60-second window, ``requests_per_minute`` budget per provider."""

    def __init__(
        self, *, requests_per_minute: int, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = requests_per_minute
        self._now = now
        # provider -> (window_start, count)
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, provider: str) -> None:
        """Record one request for ``provider``; raise :class:`RateLimited`
        if it would exceed the budget for the current window."""
        now = self._now()
        start, count = self._windows.get(provider, (now, 0))
        if now - start >= _WINDOW_SECONDS:
            start, count = now, 0
        if count >= self._limit:
            raise RateLimited(provider)
        self._windows[provider] = (start, count + 1)
