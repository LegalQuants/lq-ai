"""Live-stack wiring for the injection harness (DE-239).

Reuses DE-231's ``GoldenClient`` (the auth + chat-send plumbing) verbatim
— this module only supplies an injection-scoped guard and configuration so
the two harnesses opt in independently. Same fail-restrictive shape as the
golden harness: without the explicit opt-in AND gateway readiness AND api
credentials, every live injection test skips cleanly in keyless mode.
An explicitly enabled but incomplete run is invalid (see conftest.py).

Environment:

* ``LQ_INJECTION_LIVE=1``       — enable live injection tests (off by default).
* ``LQ_EVAL_GATEWAY_READY=1`` — operator confirms a configured, booted gateway.
  Provider keys belong to the gateway, never this process.
* ``LQ_INJECTION_PASSWORD``     — api password (required; no default).
* ``LQ_INJECTION_API_URL``      — api base URL (default http://127.0.0.1:8000).
* ``LQ_INJECTION_EMAIL``        — api login (default admin@lq.ai).
* ``LQ_INJECTION_MODEL``        — model alias for sends (default "smart").
* ``LQ_INJECTION_TIMEOUT``      — per-request timeout seconds (default 600).
* ``LQ_INJECTION_REPORT_DIR``   — where per-attack + summary reports go
  (default ``injection-report`` under the current working directory).
"""

from __future__ import annotations

import os

from tests.golden.live_client import (
    DEFAULT_API_URL,
    DEFAULT_EMAIL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    GoldenClient,
    LiveConfig,
)

DEFAULT_REPORT_DIR = "injection-report"


def injection_skip_reason() -> str | None:
    """Why live injection tests must be skipped, or ``None`` to run them."""

    if os.environ.get("LQ_INJECTION_LIVE") != "1":
        return "live injection tests disabled (set LQ_INJECTION_LIVE=1 to enable)"
    if os.environ.get("LQ_EVAL_GATEWAY_READY") != "1":
        return "gateway readiness not confirmed (set LQ_EVAL_GATEWAY_READY=1 after stack boot)"
    if not os.environ.get("LQ_INJECTION_PASSWORD"):
        return "LQ_INJECTION_PASSWORD not set (api credentials required for the chat-send path)"
    return None


def injection_config() -> LiveConfig:
    """Build a golden ``LiveConfig`` from the injection-scoped environment."""

    return LiveConfig(
        api_url=os.environ.get("LQ_INJECTION_API_URL", DEFAULT_API_URL).rstrip("/"),
        email=os.environ.get("LQ_INJECTION_EMAIL", DEFAULT_EMAIL),
        password=os.environ["LQ_INJECTION_PASSWORD"],
        model=os.environ.get("LQ_INJECTION_MODEL", DEFAULT_MODEL),
        timeout=float(os.environ.get("LQ_INJECTION_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))),
        record=False,
        skills_filter=None,
    )


def make_client() -> GoldenClient:
    return GoldenClient(injection_config())
