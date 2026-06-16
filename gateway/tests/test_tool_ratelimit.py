import pytest

from app.providers.tool.ratelimit import FixedWindowRateLimiter, RateLimited


@pytest.mark.unit
def test_allows_up_to_limit_then_refuses() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowRateLimiter(requests_per_minute=3, now=lambda: clock["t"])
    for _ in range(3):
        limiter.check("echo-test")  # no raise
    with pytest.raises(RateLimited):
        limiter.check("echo-test")


@pytest.mark.unit
def test_window_resets_after_60s() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowRateLimiter(requests_per_minute=1, now=lambda: clock["t"])
    limiter.check("echo-test")
    with pytest.raises(RateLimited):
        limiter.check("echo-test")
    clock["t"] += 61.0
    limiter.check("echo-test")  # new window, no raise


@pytest.mark.unit
def test_limits_are_per_provider() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowRateLimiter(requests_per_minute=1, now=lambda: clock["t"])
    limiter.check("a")
    limiter.check("b")  # different provider, independent budget
    with pytest.raises(RateLimited):
        limiter.check("a")
