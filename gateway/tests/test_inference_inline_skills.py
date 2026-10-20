"""Wave D.2 Task 3.0 — inline-body skill assembly on /v1/chat/completions.

Exercises the gateway-side wire contract introduced for the wizard's
"Try it" surface: a chat completion can carry ``lq_ai_inline_skills``
(a list of ``InlineSkillRef``) and the gateway assembles the verbatim
bodies into the system message WITHOUT a backend round-trip — the
backend's ``/internal/skills/{name}`` endpoint is never called for
inline entries.

Scenarios:

* Inline-only: a single inline skill ends up in the assembled system
  message; the response surfaces the synthesized name in
  ``lq_ai_applied_skills``.
* Mixed: catalogue + inline both flow through. Catalogue entries
  resolve as before; inline entries are appended after them and both
  appear in ``lq_ai_applied_skills`` in the right order.
* Inline body content does NOT leak as a logged INFO record (PII
  posture). The body still lands in the assembled system message that
  ships to the upstream provider — that's the whole point — but no
  application-level logger emits it.

The backend's organization-profile endpoint is mocked as 404 (no
Profile set; same posture as the existing skill_assembly tests). The
Anthropic provider is mocked end-to-end so we can capture and assert
on the assembled system message.
"""

from __future__ import annotations

import json as _json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.clients.backend import (
    BackendClient,
    SkillCache,
    set_backend_client,
)
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
async def gateway_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, BackendClient]]:
    """Bring the gateway up with a fresh BackendClient + cache."""

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
        app.state.routing_log = RecordingRoutingLogWriter()
        backend_client = BackendClient(
            base_url=BACKEND_URL,
            gateway_key=GATEWAY_KEY,
            cache=SkillCache(ttl_seconds=60.0),
        )
        app.state.backend_client = backend_client
        set_backend_client(backend_client)
        try:
            yield app, backend_client
        finally:
            await backend_client.aclose()
            set_backend_client(None)


@pytest_asyncio.fixture
async def http_client(
    gateway_app: tuple[FastAPI, BackendClient],
) -> AsyncIterator[AsyncClient]:
    app, _backend = gateway_app
    transport = ASGITransport(app=app)
    # This module sets LQ_AI_GATEWAY_KEY (the backend client needs it), which
    # also arms the /v1 router's require_gateway_key dependency — so the inbound
    # requests have to carry the header too.
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-LQ-AI-Gateway-Key": GATEWAY_KEY},
    ) as ac:
        yield ac


def _mock_no_org_profile() -> None:
    """Stub the Profile endpoint as 'no Profile set' (D4 default state)."""

    respx.get(f"{BACKEND_URL}/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "not_found",
                    "message": "no profile",
                    "details": {"resource": "organization_profile"},
                }
            },
        )
    )


def _mock_catalogue_skill(name: str, body: str) -> None:
    respx.get(f"{BACKEND_URL}/api/v1/internal/skills/{name}").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": name,
                "version": "1.0.0",
                "scope": "builtin",
                "title": name.title(),
                "description": f"Test skill {name}",
                "content_md": body,
                "content_yaml": f"name: {name}\n",
                "reference_files": [],
            },
        )
    )


def _anthropic_capture(captured: dict[str, object]) -> object:
    """Build a respx side_effect that captures the request body."""

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_inline_test",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 5},
            },
        )

    return _capture


@pytest.mark.integration
@respx.mock
async def test_inline_body_skill_assembled_without_backend_fetch(
    http_client: AsyncClient,
) -> None:
    """An inline-only request never hits ``/internal/skills/*``."""

    _mock_no_org_profile()
    captured: dict[str, object] = {}
    catalogue_route = respx.get(f"{BACKEND_URL}/api/v1/internal/skills/__inline__abc12345")
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=_anthropic_capture(captured)
    )

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hello"}],
            "lq_ai_inline_skills": [
                {
                    "name": "__inline__abc12345",
                    "body": "# Inline Try-It Draft\n\n1. Spot weird clauses.\n2. Suggest fixes.",
                    "source": "wizard-tryout",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    # Catalogue endpoint never called for the synthesized name.
    assert not catalogue_route.called, "inline skills must not trigger a backend fetch"

    # Assembled body reached Anthropic.
    body = captured["body"]
    assert isinstance(body, dict)
    system = body["system"]
    assert isinstance(system, str)
    assert "Inline Try-It Draft" in system
    assert "Spot weird clauses." in system

    # Applied-skills surfaces the synthesized name.
    response_body = response.json()
    assert response_body["lq_ai_applied_skills"] == ["__inline__abc12345"]


@pytest.mark.integration
@respx.mock
async def test_inline_and_catalogue_skills_both_assemble(
    http_client: AsyncClient,
) -> None:
    """Mixed lq_ai_skills + lq_ai_inline_skills: both end up in the system msg.

    Order contract: catalogue first, then inline. lq_ai_applied_skills
    reflects the same order.
    """

    _mock_no_org_profile()
    _mock_catalogue_skill("nda-review", "Catalogue NDA body content")
    captured: dict[str, object] = {}
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=_anthropic_capture(captured)
    )

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hello"}],
            "lq_ai_skills": ["nda-review"],
            "lq_ai_inline_skills": [
                {
                    "name": "__inline__deadbeef",
                    "body": "Inline draft body alpha",
                    "source": "wizard-tryout",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    body = captured["body"]
    assert isinstance(body, dict)
    system = body["system"]
    assert isinstance(system, str)
    # Both bodies present.
    assert "Catalogue NDA body content" in system
    assert "Inline draft body alpha" in system
    # Catalogue first.
    assert system.index("Catalogue NDA body content") < system.index("Inline draft body alpha")

    # Applied-skills ordering matches.
    response_body = response.json()
    assert response_body["lq_ai_applied_skills"] == ["nda-review", "__inline__deadbeef"]


@pytest.mark.integration
@respx.mock
async def test_inline_body_input_substitution(http_client: AsyncClient) -> None:
    """``inputs`` on an inline ref substitute into the body."""

    _mock_no_org_profile()
    captured: dict[str, object] = {}
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=_anthropic_capture(captured)
    )

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_inline_skills": [
                {
                    "name": "__inline__substitute",
                    "body": "Review {{document}} from the perspective of {{role}}.",
                    "inputs": {"document": "an NDA", "role": "discloser"},
                    "source": "wizard-tryout",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = captured["body"]
    assert isinstance(body, dict)
    system = body["system"]
    assert "Review an NDA from the perspective of discloser." in system


@pytest.mark.integration
@respx.mock
async def test_empty_inline_skills_preserves_legacy_no_op(
    http_client: AsyncClient,
) -> None:
    """No skills + no inline_skills → no assembly, no system message added."""

    _mock_no_org_profile()
    captured: dict[str, object] = {}
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=_anthropic_capture(captured)
    )

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "bare prompt"}],
            # Both lists empty.
            "lq_ai_skills": [],
            "lq_ai_inline_skills": [],
        },
    )
    assert response.status_code == 200, response.text
    body = captured["body"]
    assert isinstance(body, dict)
    # No system message synthesized (pre-D.2 behavior preserved).
    assert "system" not in body or body.get("system") in (None, "")


@pytest.mark.integration
@respx.mock
async def test_inline_body_tier_floor_honored(
    http_client: AsyncClient,
) -> None:
    """``minimum_inference_tier`` on an inline ref drives D1 refusal."""

    _mock_no_org_profile()

    # The smart alias resolves to anthropic/claude-opus-4-7 at tier 4 in
    # gateway.yaml.example. Under PRD §1.5.2 (lower number = stronger),
    # an inline skill declaring `minimum_inference_tier: 3` requires
    # Tier 3 or stronger; Tier 4 is weaker, so the gateway must refuse
    # (resolved=4 > floor=3) — proving the inline ref's tier
    # participates in floor resolution exactly like a catalogue skill.
    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_inline_skills": [
                {
                    "name": "__inline__floor",
                    "body": "Restricted skill",
                    "minimum_inference_tier": 3,
                    "source": "wizard-tryout",
                }
            ],
        },
    )
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["error"]["code"] == "tier_below_minimum"
    assert body["error"]["details"]["required_tier"] == 3


@pytest.mark.integration
@respx.mock
async def test_inline_body_not_logged_at_info(
    http_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Defense-in-depth: inline body text never appears in INFO+ logs.

    The body is user-supplied content (possibly PII); the gateway must
    not surface it in operational logs. The synthesized name + tier
    are safe and may appear, but the body itself must not.
    """

    _mock_no_org_profile()
    captured: dict[str, object] = {}
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=_anthropic_capture(captured)
    )

    needle = "SECRET-INLINE-BODY-TOKEN-ZX99"
    with caplog.at_level(logging.INFO):
        response = await http_client.post(
            "/v1/chat/completions",
            json={
                "model": "smart",
                "messages": [{"role": "user", "content": "hi"}],
                "lq_ai_inline_skills": [
                    {
                        "name": "__inline__redaction",
                        "body": f"Confidential note: {needle}\nDo redact.",
                        "source": "wizard-tryout",
                    }
                ],
            },
        )
    assert response.status_code == 200, response.text
    # The body MUST reach Anthropic (point of the feature).
    body = captured["body"]
    assert isinstance(body, dict)
    assert needle in body["system"]
    # But it must NOT appear in any INFO/WARN/ERROR log record.
    for record in caplog.records:
        if record.levelno >= logging.INFO:
            assert needle not in record.getMessage(), (
                f"inline body text leaked into log record {record.name}: {record.getMessage()!r}"
            )


@pytest.mark.integration
@respx.mock
async def test_oversize_inline_body_4xx_does_not_echo_body_content(
    http_client: AsyncClient,
) -> None:
    """Wave D.2 Task 3.0 security — the 4xx error envelope returned for
    an oversize inline-skill ``body`` MUST NOT echo the submitted body.

    Regression for the C2 finding in the Task 3.0 code+security review:
    pydantic's ``exc.errors()`` includes the offending ``input`` payload
    by default, so a ``string_too_long`` failure on a 64K+1-byte inline
    body returned the FULL submitted body verbatim to the caller in the
    gateway's error envelope.

    Fix: pass ``include_input=False`` to ``exc.errors()`` at the
    schema-validation rescue site in ``gateway/app/api/inference.py``.
    """

    _mock_no_org_profile()
    # Sentinel marker so the assertion is unambiguous — must not appear
    # anywhere else in the gateway implementation or test fixtures.
    sentinel = "S3CR3T-INLINE-BODY-LEAK-TEST-GATEWAY-"
    # Gateway-side cap is 64 KB per InlineSkillRef.body.
    oversize_body = sentinel * ((64 * 1024 // len(sentinel)) + 2)
    assert len(oversize_body) > 64 * 1024

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_inline_skills": [
                {
                    "name": "__inline__oversize",
                    "body": oversize_body,
                    "source": "wizard-tryout",
                }
            ],
        },
    )
    # Validation failure surfaces as 4xx (the gateway wraps as 400).
    assert 400 <= response.status_code < 500, response.status_code

    body_text = response.text
    # CRITICAL: the submitted inline body sentinel must not appear in
    # the response envelope.
    assert sentinel not in body_text, (
        "Inline-body content leaked back in the gateway error envelope — "
        "pydantic input echo is not suppressed at the validation rescue site."
    )
    # Useful error identifier MUST still be present.
    assert "string_too_long" in body_text or "body" in body_text, (
        f"Error envelope is missing a useful identifier; got: {body_text!r}"
    )


@pytest.mark.integration
@respx.mock
async def test_lq_ai_inline_skills_over_cap_returns_4xx(
    http_client: AsyncClient,
) -> None:
    """Wave D.2 Task 3.0 (I1) — ``lq_ai_inline_skills`` list is capped at 16.

    Regression for the I1 finding: without a cap, a single chat
    completion could attach thousands of inline refs x 64 KB each and
    force the gateway to assemble a multi-megabyte system prompt
    (workload-multiplication DoS).
    """

    _mock_no_org_profile()
    over_cap = [
        {
            "name": f"__inline__cap{i:02d}",
            "body": "tiny body",
            "source": "wizard-tryout",
        }
        for i in range(17)
    ]

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_inline_skills": over_cap,
        },
    )
    assert 400 <= response.status_code < 500, response.text
    body_text = response.text
    assert "too_long" in body_text or "lq_ai_inline_skills" in body_text, body_text


@pytest.mark.integration
@respx.mock
async def test_lq_ai_skills_over_cap_returns_4xx(http_client: AsyncClient) -> None:
    """Wave D.2 Task 3.0 (I1) — catalogue ``lq_ai_skills`` is capped at 16.

    Symmetrical to the inline cap; the catalogue path also multiplies
    workload (one backend round-trip per slug) so the same bound
    applies."""

    _mock_no_org_profile()
    over_cap = [f"skill-{i:02d}" for i in range(17)]

    response = await http_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_skills": over_cap,
        },
    )
    assert 400 <= response.status_code < 500, response.text
    body_text = response.text
    assert "too_long" in body_text or "lq_ai_skills" in body_text, body_text
