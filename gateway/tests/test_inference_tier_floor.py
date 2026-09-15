"""Integration tests for D1 tier-floor refusal on the chat-completions surface.

Maps to PRD §4.4 / D1 verification cases (a)-(d).

Under PRD §1.5.2: lower tier number = stronger security.
``minimum_inference_tier=N`` means "require Tier N or stronger (≤N)."
A request is refused when the resolved tier is weaker (higher-numbered)
than the declared floor.

The ``smart`` alias resolves to Tier 4 in ``gateway.yaml.example``.

* (a) Request override: ``minimum_inference_tier=3`` against ``smart``
  (tier 4) → HTTP 403.  Tier 4 is weaker than the Tier 3 floor.
* (b) Skill floor: a skill with ``minimum_inference_tier=3`` attached to a
  request routed to tier 4 → HTTP 403; ``details.source`` names the skill.
* (c) Project floor: ``lq_ai_project_minimum_inference_tier=3`` against
  tier-4 model → HTTP 403; ``details.source == "project"``.
* (d) Audit log: a refused request writes a row with ``refused=True`` and
  ``refusal_reason`` carrying ``tier_below_minimum``.

Plus the negative cases (the floor passes; the request flows to the
upstream and writes a normal log row) as a guard against over-refusal.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.clients.backend import BackendClient, SkillCache, set_backend_client
from app.routing_log import RecordingRoutingLogWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"

BACKEND_URL = "http://api.test"
GATEWAY_KEY = "test-gateway-key-correct-horse"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def gateway_with_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, RecordingRoutingLogWriter, BackendClient]]:
    """Bring up the gateway with a respx-mockable BackendClient + recorder."""

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")
    monkeypatch.setenv("LQ_AI_API_URL", BACKEND_URL)
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", GATEWAY_KEY)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.main import app

    async with _run_lifespan(app):
        recorder = RecordingRoutingLogWriter()
        app.state.routing_log = recorder
        backend_client = BackendClient(
            base_url=BACKEND_URL,
            gateway_key=GATEWAY_KEY,
            cache=SkillCache(ttl_seconds=60.0),
        )
        app.state.backend_client = backend_client
        set_backend_client(backend_client)
        try:
            yield app, recorder, backend_client
        finally:
            await backend_client.aclose()
            set_backend_client(None)


@pytest_asyncio.fixture
async def http_client(
    gateway_with_backend: tuple[FastAPI, RecordingRoutingLogWriter, BackendClient],
) -> AsyncIterator[tuple[AsyncClient, RecordingRoutingLogWriter]]:
    app, recorder, _backend = gateway_with_backend
    transport = ASGITransport(app=app)
    # This module sets LQ_AI_GATEWAY_KEY (the backend client needs it), which
    # also arms the /v1 router's require_gateway_key dependency — so the inbound
    # requests have to carry the header too.
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-LQ-AI-Gateway-Key": GATEWAY_KEY},
    ) as ac:
        yield ac, recorder


def _mock_skill(name: str, *, minimum_inference_tier: int | None) -> None:
    """Register a respx stub for ``GET /api/v1/internal/skills/{name}``.

    Side-effect: also installs a default 404 stub for the Organization
    Profile endpoint (D4) so the prompt-assembly path's Profile fetch
    sees "no Profile set" and proceeds unchanged. Tier-floor tests
    don't care about the Profile; the 404 stub is the simplest way to
    keep them isolated from D4 behavior.
    """

    respx.get(f"{BACKEND_URL}/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "not_found",
                    "message": "No Organization Profile is set for this deployment.",
                }
            },
        )
    )

    payload: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "scope": "builtin",
        "title": name.title(),
        "description": f"Test skill {name}",
        "content_md": f"# {name}\n\nBody.",
        "content_yaml": f"name: {name}\ndescription: ...\n",
        "reference_files": [],
    }
    if minimum_inference_tier is not None:
        payload["minimum_inference_tier"] = minimum_inference_tier
    respx.get(f"{BACKEND_URL}/api/v1/internal/skills/{name}").mock(
        return_value=httpx.Response(200, json=payload)
    )


def _mock_anthropic_success() -> respx.Route:
    """Mock the upstream Anthropic call with a benign 200 response."""

    return respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_d1",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )


# --- Case (a): request override --------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_a_request_override_stricter_than_resolved_tier_refuses(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """(a) Request floor 3 against tier-4 ``smart`` → 403 + tier_below_minimum.

    Under PRD §1.5.2, Tier 4 is weaker than the Tier 3 floor, so the
    request is refused (resolved_tier=4 > floor=3).
    """

    client, _recorder = http_client
    upstream = _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "minimum_inference_tier": 3,
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "tier_below_minimum"
    details = body["error"]["details"]
    assert details["required_tier"] == 3
    assert details["resolved_tier"] == 4
    assert details["source"] == "request"
    assert details["routed_provider"] == "anthropic-prod"
    # Refusal MUST happen before any upstream call.
    assert upstream.called is False


@pytest.mark.integration
@respx.mock
async def test_a_request_override_weaker_floor_passes(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """Request floor at 5 (weakest) against tier-4 ``smart`` → 200 (no refusal).

    Under PRD §1.5.2, floor=5 means "Tier 5 or stronger is acceptable."
    Tier 4 is stronger than Tier 5, so the request is allowed.
    """

    client, recorder = http_client
    _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "minimum_inference_tier": 5,
        },
    )
    assert response.status_code == 200
    # The audit row exists and is NOT marked refused.
    assert len(recorder.rows) == 1
    assert recorder.rows[0].refused is False


@pytest.mark.integration
@respx.mock
async def test_a_request_override_equal_tier_passes(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """Floor==resolved tier is a passing case (floor is the weakest acceptable)."""

    client, _recorder = http_client
    _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "minimum_inference_tier": 4,
        },
    )
    assert response.status_code == 200


# --- Case (b): skill floor --------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_b_skill_floor_stricter_than_resolved_tier_refuses(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """(b) Skill with min_tier=3 attached to ``smart`` (tier 4) → 403.

    Under PRD §1.5.2, the skill requires Tier 3 or stronger. The ``smart``
    alias resolves to Tier 4 (weaker), so the request is refused.
    """

    client, _recorder = http_client
    _mock_skill("strict-skill", minimum_inference_tier=3)
    upstream = _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_skills": ["strict-skill"],
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "tier_below_minimum"
    details = body["error"]["details"]
    assert details["required_tier"] == 3
    assert details["resolved_tier"] == 4
    assert details["source"] == "skill:strict-skill"
    assert upstream.called is False


@pytest.mark.integration
@respx.mock
async def test_b_skill_without_floor_does_not_refuse(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """A skill with no declared floor lets the request through."""

    client, _recorder = http_client
    _mock_skill("plain-skill", minimum_inference_tier=None)
    _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_skills": ["plain-skill"],
        },
    )
    assert response.status_code == 200


# --- Case (c): project floor ------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_c_project_floor_stricter_than_resolved_tier_refuses(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """(c) Project floor 3 against tier-4 ``smart`` → 403; source=project.

    Under PRD §1.5.2, a privileged project with floor=3 requires Tier 3
    or stronger. Tier 4 (``smart``) is weaker — refused.
    """

    client, _recorder = http_client
    upstream = _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_project_minimum_inference_tier": 3,
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "tier_below_minimum"
    details = body["error"]["details"]
    assert details["required_tier"] == 3
    assert details["resolved_tier"] == 4
    assert details["source"] == "project"
    assert upstream.called is False


# --- Case (d): audit log captures refusal -----------------------------------


@pytest.mark.integration
@respx.mock
async def test_d_refusal_writes_audit_row_with_refused_true(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """(d) A refused request writes one row with ``refused=True`` and reason.

    floor=3 against tier-4 ``smart`` → refused (Tier 4 is weaker than Tier 3).
    """

    client, recorder = http_client
    _mock_anthropic_success()

    await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "minimum_inference_tier": 3,
        },
    )

    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    assert row.refused is True
    assert row.refusal_reason is not None
    assert "tier_below_minimum" in row.refusal_reason
    assert "required=3" in row.refusal_reason
    assert "resolved=4" in row.refusal_reason
    assert "source=request" in row.refusal_reason
    # The row carries the *primary* candidate's tier so operators see
    # what the request was about to route to.
    assert row.routed_inference_tier == 4
    assert row.routed_provider == "anthropic-prod"
    assert row.requested_model == "smart"


# --- Most-restrictive wins across sources -----------------------------------


@pytest.mark.integration
@respx.mock
async def test_most_restrictive_source_wins(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """Request=4, project=3, skill=2 → min=2 wins; source=skill.

    Under PRD §1.5.2, lower number = stricter. The skill's floor=2 is the
    most restrictive, so it governs. Tier 4 (``smart``) is weaker than
    floor=2 → 403.
    """

    client, _recorder = http_client
    _mock_skill("strict", minimum_inference_tier=2)
    upstream = _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "minimum_inference_tier": 4,
            "lq_ai_project_minimum_inference_tier": 3,
            "lq_ai_skills": ["strict"],
        },
    )
    assert response.status_code == 403
    details = response.json()["error"]["details"]
    assert details["required_tier"] == 2
    assert details["source"] == "skill:strict"
    assert upstream.called is False


# --- Streaming refusal ------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_streaming_refusal_returns_403_not_sse(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """Streaming requests get the same JSON 403 envelope, not an SSE error.

    Refusal happens before the streaming path forks, so the caller sees
    a plain JSON response body — no half-opened SSE stream.
    """

    client, recorder = http_client
    upstream = _mock_anthropic_success()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "minimum_inference_tier": 3,
            "stream": True,
        },
    )

    assert response.status_code == 403
    # JSON envelope (not text/event-stream).
    assert "application/json" in response.headers.get("content-type", "")
    body = json.loads(response.content)
    assert body["error"]["code"] == "tier_below_minimum"
    assert upstream.called is False
    assert recorder.rows[0].refused is True
