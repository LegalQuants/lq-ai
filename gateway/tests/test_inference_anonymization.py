"""M2-B3 end-to-end: anonymization wired into chat-completions handler.

These tests exercise the full request → middleware → provider → response
loop, asserting:

* The provider receives **pseudonymized** content on the request path.
* The client receives **rehydrated** content on the response path.
* The routing-log row carries ``anonymization_applied=True``.
* Skip conditions (config disabled, tier mismatch, ``privileged``,
  per-request ``anonymize: false``) leave content and audit untouched.

The Anonymizer is stubbed via ``app.state.anonymizer`` so spaCy stays
off the fast feedback path. End-to-end correctness with the real
Presidio engine is covered in ``tests/anonymization/test_engine_integration.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.anonymization.engine import Anonymizer
from app.clients.backend import BackendClient, SkillCache, set_backend_client
from app.routing_log import RecordingRoutingLogWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"

BACKEND_URL = "http://api.test"
GATEWAY_KEY = "test-gateway-key-correct-horse"


# ---------------------------------------------------------------------------
# Stub analyzer — matches the shape used in tests/anonymization/test_anonymizer.py.
# Returns canned spans keyed by exact input text so each pseudonymize call
# resolves deterministically.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    entity_type: str
    start: int
    end: int
    score: float = 0.85


class _StubAnalyzer:
    def __init__(self, by_text: dict[str, list[_Span]]) -> None:
        self._by_text = by_text

    def analyze(self, *, text: str, language: str = "en", **_kwargs: object) -> list[_Span]:
        return list(self._by_text.get(text, []))


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def gateway_with_anon_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, RecordingRoutingLogWriter, BackendClient]]:
    """Bring up the gateway, then flip ``anonymization.enabled=true`` in state."""

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

        # Force the anonymization feature flag on for these tests.
        # The example ships with ``enabled=false`` so M1-era deployments
        # don't accidentally trip the M2 middleware on upgrade.
        app.state.config.anonymization.enabled = True
        # ``smart`` resolves to Tier 4 in the example config; the
        # example's apply_at_tiers is [3, 4, 5], so the tier gate is
        # already correct for the requests below.

        try:
            yield app, recorder, backend_client
        finally:
            await backend_client.aclose()
            set_backend_client(None)
            app.state.config.anonymization.enabled = False


@pytest_asyncio.fixture
async def http_client(
    gateway_with_anon_enabled: tuple[FastAPI, RecordingRoutingLogWriter, BackendClient],
) -> AsyncIterator[tuple[AsyncClient, RecordingRoutingLogWriter, FastAPI]]:
    app, recorder, _backend = gateway_with_anon_enabled
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, recorder, app


def _install_stub_anonymizer(app: FastAPI, by_text: dict[str, list[_Span]]) -> None:
    """Replace ``app.state.anonymizer`` with one wrapping a stub analyzer."""

    app.state.anonymizer = Anonymizer(analyzer=_StubAnalyzer(by_text))


def _mock_anthropic(*, response_text: str) -> respx.Route:
    """Mock Anthropic Messages with a 200 carrying ``response_text``."""

    return respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_test",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": response_text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 5},
            },
        )
    )


def _anthropic_user_content(call: respx.models.Call) -> str:
    """Extract the first user-message content from the Anthropic call body."""

    body = json.loads(call.request.content)
    for message in body.get("messages", []):
        if message.get("role") == "user":
            content = message.get("content")
            # Anthropic Messages allows ``content`` to be a string OR a
            # list of content blocks. The Anthropic adapter sends it as
            # either; we handle both.
            if isinstance(content, str):
                return content
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return str(block.get("text", ""))
    raise AssertionError("no user message in Anthropic request body")


# ---------------------------------------------------------------------------
# Happy path — non-streaming.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_non_streaming_pseudonymizes_request_and_rehydrates_response(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter, FastAPI],
) -> None:
    """Round-trip: provider sees PERSON_0001; client sees John Smith."""

    client, recorder, app = http_client
    user_msg = "John Smith signed the agreement."
    _install_stub_anonymizer(
        app,
        {
            user_msg: [_Span("PERSON", 0, 10)],
            # The model's response contains a pseudonym to be rehydrated.
            # The post-middleware rehydrates content (not the request);
            # we configure analyze() for the request text only.
        },
    )

    upstream = _mock_anthropic(response_text="PERSON_0001 has signed; the deal closes Friday.")

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",  # Tier 4 → matches apply_at_tiers=[3,4,5]
            "messages": [{"role": "user", "content": user_msg}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Response content is rehydrated: PERSON_0001 → John Smith.
    assert (
        body["choices"][0]["message"]["content"] == "John Smith has signed; the deal closes Friday."
    )
    assert body["anonymization_applied"] is True

    # The Anthropic adapter received the pseudonymized request.
    assert upstream.called
    sent_to_provider = _anthropic_user_content(upstream.calls.last)
    assert sent_to_provider == "PERSON_0001 signed the agreement."

    # Audit log row carries the flag.
    assert len(recorder.rows) == 1
    assert recorder.rows[0].anonymization_applied is True


# ---------------------------------------------------------------------------
# Skip conditions — non-streaming.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_per_request_anonymize_false_skips_middleware(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter, FastAPI],
) -> None:
    """``anonymize: false`` passes content through untouched + audit flag False."""

    client, recorder, app = http_client
    user_msg = "John Smith signed the agreement."
    _install_stub_anonymizer(app, {user_msg: [_Span("PERSON", 0, 10)]})

    upstream = _mock_anthropic(response_text="ack")

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": user_msg}],
            "anonymize": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["anonymization_applied"] is False
    assert upstream.called
    # Provider sees the raw name when caller opts out.
    assert _anthropic_user_content(upstream.calls.last) == user_msg
    # Audit reflects skip.
    assert recorder.rows[0].anonymization_applied is False


@pytest.mark.integration
@respx.mock
async def test_privileged_request_skips_middleware(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter, FastAPI],
) -> None:
    """``lq_ai_privileged: true`` skips even when anonymization is enabled.

    Decision A: privileged chats are never rewritten because rewriting
    privileged work product risks corrupting it.
    """

    client, recorder, app = http_client
    user_msg = "John Smith signed the agreement."
    _install_stub_anonymizer(app, {user_msg: [_Span("PERSON", 0, 10)]})

    upstream = _mock_anthropic(response_text="ack")

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": user_msg}],
            "lq_ai_privileged": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["anonymization_applied"] is False
    assert _anthropic_user_content(upstream.calls.last) == user_msg
    assert recorder.rows[0].anonymization_applied is False


@pytest.mark.integration
@respx.mock
async def test_tier_outside_apply_at_tiers_skips_middleware(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter, FastAPI],
) -> None:
    """Tier gating: a routed tier outside ``apply_at_tiers`` skips substitution.

    Rather than routing to a different (Tier 1) alias — which would
    require coupling this test to whichever model the operator happens
    to have loaded in Ollama at test time — we keep the ``smart`` (Tier
    4) routing and narrow ``apply_at_tiers`` to ``[5]`` so the gate
    closes for this run. Same skip semantics, simpler dependencies.
    """

    client, recorder, app = http_client
    user_msg = "John Smith signed the agreement."
    _install_stub_anonymizer(app, {user_msg: [_Span("PERSON", 0, 10)]})

    # Narrow the tier gate so the routed tier (4) is excluded.
    app.state.config.anonymization.apply_at_tiers = [5]

    upstream = _mock_anthropic(response_text="ack")

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": user_msg}],
        },
    )

    assert response.status_code == 200
    assert response.json()["anonymization_applied"] is False
    assert upstream.called
    # Provider sees the raw name when tier gate closes.
    assert _anthropic_user_content(upstream.calls.last) == user_msg
    assert recorder.rows[0].anonymization_applied is False


# ---------------------------------------------------------------------------
# Streaming path — pseudonyms straddling SSE chunk boundaries are rehydrated.
# ---------------------------------------------------------------------------


def _mock_anthropic_streaming(*, deltas: list[str]) -> respx.Route:
    """Mock Anthropic Messages SSE with a sequence of text deltas.

    Emits a minimal valid stream: message_start → content_block_start →
    one content_block_delta per text fragment → content_block_stop →
    message_delta → message_stop. Each frame is a real SSE event so
    httpx returns it as an aiter_bytes()-able stream.
    """

    lines: list[str] = []
    lines.append(
        "event: message_start\n"
        + "data: "
        + json.dumps(
            {
                "type": "message_start",
                "message": {
                    "id": "msg_stream",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "claude-opus-4-7",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 0},
                },
            }
        )
        + "\n\n"
    )
    lines.append(
        "event: content_block_start\n"
        + "data: "
        + json.dumps(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
        )
        + "\n\n"
    )
    for delta in deltas:
        lines.append(
            "event: content_block_delta\n"
            + "data: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": delta},
                }
            )
            + "\n\n"
        )
    lines.append(
        "event: content_block_stop\n"
        + "data: "
        + json.dumps({"type": "content_block_stop", "index": 0})
        + "\n\n"
    )
    lines.append(
        "event: message_delta\n"
        + "data: "
        + json.dumps(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            }
        )
        + "\n\n"
    )
    lines.append("event: message_stop\n" + "data: " + json.dumps({"type": "message_stop"}) + "\n\n")

    body = "".join(lines).encode()
    return respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )
    )


def _collect_sse_content(body: bytes) -> str:
    """Extract concatenated ``choices[0].delta.content`` from SSE bytes."""

    out: list[str] = []
    for line in body.decode().splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :].strip()
        if payload == "[DONE]" or not payload:
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in obj.get("choices", []):
            content = choice.get("delta", {}).get("content")
            if content:
                out.append(content)
    return "".join(out)


@pytest.mark.integration
@respx.mock
async def test_streaming_rehydrates_pseudonyms_across_chunk_boundaries(
    http_client: tuple[AsyncClient, RecordingRoutingLogWriter, FastAPI],
) -> None:
    """SSE deltas split across PERSON_0001 boundary surface as ``John Smith``."""

    client, recorder, app = http_client
    user_msg = "John Smith signed the agreement."
    _install_stub_anonymizer(app, {user_msg: [_Span("PERSON", 0, 10)]})

    # The model streams ``PERSON_0001 ack`` split across three deltas
    # such that the pseudonym is partial in two of them.
    _mock_anthropic_streaming(deltas=["Hello PERSON_", "0001", " ack."])

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": user_msg}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    content = _collect_sse_content(response.content)
    assert content == "Hello John Smith ack."
    assert recorder.rows[0].anonymization_applied is True
