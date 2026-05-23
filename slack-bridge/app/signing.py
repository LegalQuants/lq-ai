"""Slack request-signature verification.

Slack signs every webhook request with HMAC-SHA256 over the literal
string ``v0:{timestamp}:{body}`` using the App's signing secret. The
result is sent in the ``X-Slack-Signature`` header prefixed with
``v0=``; the corresponding timestamp is in ``X-Slack-Request-Timestamp``.

Verifying signatures is the substrate for every inbound webhook the
bridge ever handles. M3-D2's slash-command handler (descoped to M4 /
community per DE-288) will lean on this primitive. We ship it now so
when the slash-command surface lands it sits on a verified
foundation.

Replay protection: Slack recommends rejecting any request with a
timestamp older than 5 minutes from the current time. We enforce that
here so the protocol-level invariant lives in one place.

References:
- https://api.slack.com/authentication/verifying-requests-from-slack
"""

from __future__ import annotations

import hashlib
import hmac
import time

_MAX_AGE_SECONDS = 5 * 60


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: int | None = None,
) -> bool:
    """Return True when the request's HMAC matches and the timestamp
    is within the freshness window.

    All four input types are deliberately strict:

    * ``signing_secret`` — operator-supplied via ``SLACK_SIGNING_SECRET``
      env var.
    * ``timestamp`` — raw ``X-Slack-Request-Timestamp`` header value
      (a Unix epoch as a string; Slack does not zero-pad).
    * ``body`` — raw request body bytes (NOT the json-decoded form;
      Slack signs the raw bytes).
    * ``signature`` — the full ``X-Slack-Signature`` header including
      the ``v0=`` prefix.

    The ``now`` parameter is for testing — production code passes
    ``None`` and the function reads the wall clock.

    Returns False (not an exception) on any failure path so the caller
    can return 401 without leaking which check failed.
    """

    if not (signing_secret and timestamp and signature and signature.startswith("v0=")):
        return False

    try:
        ts_int = int(timestamp)
    except ValueError:
        return False

    current = now if now is not None else int(time.time())
    if abs(current - ts_int) > _MAX_AGE_SECONDS:
        return False

    base = f"v0:{timestamp}:".encode() + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)
