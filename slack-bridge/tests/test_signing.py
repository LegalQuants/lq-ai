"""Slack signature verification — M3-D1.

Targets :func:`app.signing.verify_slack_signature` which gates every
inbound webhook the bridge handles. The substrate matters because
M3-D2's slash-command handler (descoped to M4 per DE-288) will lean
on it; if signature verification ever passes a forged request, the
slash-command surface inherits the gap.

The vectors below are constructed by hand rather than copied from
Slack's docs so the test exercises the exact HMAC computation the
bridge runs.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from app.signing import verify_slack_signature

SECRET = "12345678901234567890123456789012"
NOW = 1_700_000_000


def _sign(secret: str, timestamp: int, body: bytes) -> str:
    base = f"v0:{timestamp}:".encode() + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_valid_signature_accepts() -> None:
    body = b'{"type":"event_callback"}'
    sig = _sign(SECRET, NOW, body)
    assert verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(NOW),
        body=body,
        signature=sig,
        now=NOW,
    )


def test_tampered_body_rejects() -> None:
    body = b'{"type":"event_callback"}'
    sig = _sign(SECRET, NOW, body)
    tampered = b'{"type":"different"}'
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(NOW),
        body=tampered,
        signature=sig,
        now=NOW,
    )


def test_wrong_secret_rejects() -> None:
    body = b'{"type":"event_callback"}'
    sig = _sign(SECRET, NOW, body)
    assert not verify_slack_signature(
        signing_secret="x" * 32,
        timestamp=str(NOW),
        body=body,
        signature=sig,
        now=NOW,
    )


def test_stale_timestamp_rejects() -> None:
    body = b'{"type":"event_callback"}'
    stale_ts = NOW - (6 * 60)  # 6 minutes old — beyond the 5-minute window
    sig = _sign(SECRET, stale_ts, body)
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(stale_ts),
        body=body,
        signature=sig,
        now=NOW,
    )


def test_future_timestamp_rejects() -> None:
    """Symmetric to the stale check — a far-future timestamp is also
    out of the freshness window (clock skew or replay attack)."""

    body = b'{"type":"event_callback"}'
    future_ts = NOW + (6 * 60)
    sig = _sign(SECRET, future_ts, body)
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(future_ts),
        body=body,
        signature=sig,
        now=NOW,
    )


def test_missing_prefix_rejects() -> None:
    """A signature without the ``v0=`` prefix is malformed."""

    body = b'{"type":"event_callback"}'
    sig = _sign(SECRET, NOW, body).removeprefix("v0=")
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(NOW),
        body=body,
        signature=sig,
        now=NOW,
    )


def test_empty_inputs_reject() -> None:
    """Every empty-string input should return False rather than raise."""

    body = b""
    assert not verify_slack_signature(
        signing_secret="",
        timestamp=str(NOW),
        body=body,
        signature="v0=" + "0" * 64,
        now=NOW,
    )
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp="",
        body=body,
        signature="v0=" + "0" * 64,
        now=NOW,
    )
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(NOW),
        body=body,
        signature="",
        now=NOW,
    )


def test_real_wall_clock_path() -> None:
    """``now=None`` reads ``time.time()`` — sanity check that the
    default path works with a freshly-signed request."""

    ts = int(time.time())
    body = b'{"type":"event_callback"}'
    sig = _sign(SECRET, ts, body)
    assert verify_slack_signature(
        signing_secret=SECRET,
        timestamp=str(ts),
        body=body,
        signature=sig,
    )
