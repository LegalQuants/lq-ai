"""Tests for the Redis-backed login rate limiter.

Pen-test 2026-09-25 finding (HIGH): the login surface had no throttle. The
limiter counts hits per key in a fixed window and fails open on Redis errors.
"""

from __future__ import annotations

import pytest

from app.security import rate_limit


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


class _BrokenRedis:
    async def incr(self, key: str) -> int:
        raise ConnectionError("redis down")


@pytest.mark.unit
async def test_allows_up_to_limit_then_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(rate_limit, "get_redis", lambda: fake)

    # First `limit` calls are allowed (return None).
    for _ in range(3):
        assert (
            await rate_limit.check_rate_limit("login:1.2.3.4", limit=3, window_seconds=900) is None
        )

    # The 4th call exceeds the limit and returns a positive retry-after.
    retry = await rate_limit.check_rate_limit("login:1.2.3.4", limit=3, window_seconds=900)
    assert isinstance(retry, int) and retry > 0


@pytest.mark.unit
async def test_expiry_armed_on_first_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(rate_limit, "get_redis", lambda: fake)
    await rate_limit.check_rate_limit("login:9.9.9.9", limit=5, window_seconds=600)
    assert fake.ttls["ratelimit:login:9.9.9.9"] == 600


@pytest.mark.unit
async def test_separate_keys_have_independent_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(rate_limit, "get_redis", lambda: fake)
    for _ in range(3):
        await rate_limit.check_rate_limit("login:a", limit=3, window_seconds=900)
    # A different key is unaffected.
    assert await rate_limit.check_rate_limit("login:b", limit=3, window_seconds=900) is None


@pytest.mark.unit
async def test_fails_open_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "get_redis", lambda: _BrokenRedis())
    # Even far over any limit, a Redis failure must allow the request.
    for _ in range(10):
        assert await rate_limit.check_rate_limit("login:x", limit=1, window_seconds=900) is None
