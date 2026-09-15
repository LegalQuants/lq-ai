"""Live-stack client for the skill golden harness (DE-231).

Drives a skill over a fixture through the NORMAL api chat-send path
(``POST /api/v1/chats/{id}/messages`` with ``skills=[slug]`` +
``skill_inputs``) against a running compose stack, exactly as the web UI
does. The gateway — not this client — holds the provider keys; the
client only needs api credentials.

Environment (all read by :func:`live_config`):

* ``LQ_GOLDEN_LIVE=1``      — enable live golden tests (off by default).
* ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` — at least one must be
  non-empty; the stack's gateway needs a provider to perform inference.
* ``LQ_GOLDEN_API_URL``     — api base URL (default http://127.0.0.1:8000).
* ``LQ_GOLDEN_EMAIL``       — api login (default admin@lq.ai).
* ``LQ_GOLDEN_PASSWORD``    — api password (required; no default).
* ``LQ_GOLDEN_MODEL``       — model alias for sends (default "smart").
* ``LQ_GOLDEN_TIMEOUT``     — per-request timeout seconds (default 600).
* ``LQ_GOLDEN_SKILLS``      — optional comma-separated slug filter.
* ``LQ_GOLDEN_RECORD=1``    — record mode: write observed sidecars, do
  not fail on range misses (see tests/golden/README.md).
* ``LQ_GOLDEN_REPORT_DIR``  — where failure/observation reports go
  (default ``golden-report`` under the current working directory).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .golden_lib import Fixture

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_EMAIL = "admin@lq.ai"
DEFAULT_MODEL = "smart"
DEFAULT_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class LiveConfig:
    api_url: str
    email: str
    password: str
    model: str
    timeout: float
    record: bool
    skills_filter: frozenset[str] | None


def live_skip_reason() -> str | None:
    """Why live golden tests must be skipped, or ``None`` to run them.

    Fail-restrictive: without the explicit opt-in AND a provider key AND
    credentials, every live test skips cleanly so the suite stays green
    keyless (DE-231 acceptance).
    """

    if os.environ.get("LQ_GOLDEN_LIVE") != "1":
        return "live golden tests disabled (set LQ_GOLDEN_LIVE=1 to enable)"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        return (
            "no provider key in the environment (ANTHROPIC_API_KEY or "
            "OPENAI_API_KEY) — the compose stack's gateway cannot perform inference"
        )
    if not os.environ.get("LQ_GOLDEN_PASSWORD"):
        return "LQ_GOLDEN_PASSWORD not set (api credentials required for the chat-send path)"
    return None


def live_config() -> LiveConfig:
    """Build the live configuration from the environment."""

    raw_filter = os.environ.get("LQ_GOLDEN_SKILLS", "").strip()
    skills_filter = (
        frozenset(s.strip() for s in raw_filter.split(",") if s.strip()) if raw_filter else None
    )
    return LiveConfig(
        api_url=os.environ.get("LQ_GOLDEN_API_URL", DEFAULT_API_URL).rstrip("/"),
        email=os.environ.get("LQ_GOLDEN_EMAIL", DEFAULT_EMAIL),
        password=os.environ["LQ_GOLDEN_PASSWORD"],
        model=os.environ.get("LQ_GOLDEN_MODEL", DEFAULT_MODEL),
        timeout=float(os.environ.get("LQ_GOLDEN_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))),
        record=os.environ.get("LQ_GOLDEN_RECORD") == "1",
        skills_filter=skills_filter,
    )


class GoldenClientError(RuntimeError):
    """The stack refused a request the harness depends on."""


class GoldenClient:
    """Thin synchronous client over the api's auth + chat-send endpoints."""

    def __init__(self, config: LiveConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=f"{config.api_url}/api/v1",
            timeout=httpx.Timeout(config.timeout, connect=30.0),
        )

    def close(self) -> None:
        self._http.close()

    def login(self) -> None:
        """Authenticate and install the bearer token.

        Fails loudly (rather than silently rotating credentials) if the
        first-run ``must_change_password`` gate is still active — the
        operator or workflow must clear it first; see
        .github/workflows/skill-golden.yml for the CI bootstrap step.
        """

        resp = self._http.post(
            "/auth/login",
            json={"email": self._config.email, "password": self._config.password},
        )
        if resp.status_code != 200:
            raise GoldenClientError(
                f"login failed for {self._config.email!r}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        body = resp.json()
        if body.get("user", {}).get("must_change_password"):
            raise GoldenClientError(
                "the api user still has must_change_password=True — clear the "
                "first-run gate (POST /api/v1/auth/change-password) before "
                "running golden tests; see tests/golden/README.md"
            )
        self._http.headers["Authorization"] = f"Bearer {body['access_token']}"

    def run_fixture(self, fixture: Fixture) -> dict[str, Any]:
        """Create a chat and send the fixture through the skill.

        Returns the ``MessagePostResponse`` body (non-streaming path).
        """

        create = self._http.post("/chats", json={"title": f"golden: {fixture.fixture_id}"})
        if create.status_code != 201:
            raise GoldenClientError(
                f"chat create failed: HTTP {create.status_code} {create.text[:300]}"
            )
        chat_id = create.json()["id"]

        payload: dict[str, Any] = {
            "content": fixture.message_content,
            "model": fixture.model or self._config.model,
            "skills": [fixture.skill],
            "stream": False,
        }
        if fixture.skill_inputs:
            payload["skill_inputs"] = {fixture.skill: dict(fixture.skill_inputs)}

        send = self._http.post(f"/chats/{chat_id}/messages", json=payload)
        if send.status_code != 200:
            raise GoldenClientError(
                f"chat send failed for {fixture.skill}/{fixture.fixture_id}: "
                f"HTTP {send.status_code} {send.text[:500]}"
            )
        return send.json()
