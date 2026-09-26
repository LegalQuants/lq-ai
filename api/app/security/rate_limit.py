"""Redis-backed fixed-window rate limiting for the authentication surface.

Pen-test 2026-09-25 finding (HIGH): nothing in the api throttled the login
surface, so online password / TOTP brute-force was unbounded — the threat model
claimed an ``RateLimited`` gate that was defined but never raised.

A fixed-window counter per key: ``INCR`` the key, set ``EXPIRE`` on the first
hit of the window, and refuse once the count exceeds the limit. It **fails
open** — if Redis is unavailable we log and allow the request, so an outage
degrades to "no app-level throttle" (the edge/WAF is the backstop) rather than
locking every user out.
"""

from __future__ import annotations

import logging

from app.cache import get_redis

log = logging.getLogger(__name__)


async def check_rate_limit(key: str, *, limit: int, window_seconds: int) -> int | None:
    """Count one hit against ``key``; return retry-after seconds if over limit.

    Returns ``None`` when the request is within the limit, or the number of
    seconds until the window resets when the limit is exceeded. Fails open
    (returns ``None``) on any Redis error.
    """

    redis_key = f"ratelimit:{key}"
    try:
        redis = get_redis()
        count = await redis.incr(redis_key)
        if count == 1:
            # First hit of a new window — arm the expiry.
            await redis.expire(redis_key, window_seconds)
        if count > limit:
            ttl = await redis.ttl(redis_key)
            return ttl if isinstance(ttl, int) and ttl > 0 else window_seconds
        return None
    except Exception as exc:  # fail open — availability over perfect throttling
        log.warning("rate-limit check failed for %r (allowing request): %s", key, exc)
        return None


__all__ = ["check_rate_limit"]
