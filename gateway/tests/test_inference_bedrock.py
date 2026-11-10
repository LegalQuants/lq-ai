"""Mocked HTTP gateway/lifecycle integration; not live AWS acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from cryptography.fernet import Fernet

from app.config_loader import load_config
from app.main import app, build_adapter


@pytest.mark.parametrize(
    "protocol,path,payload",
    [
        (
            "messages",
            "/anthropic/v1/messages",
            {
                "id": "msg-1",
                "model": "native",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "hello AWS"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 2, "output_tokens": 2},
            },
        ),
        (
            "chat_completions",
            "/openai/v1/chat/completions",
            {
                "id": "chat-1",
                "model": "native",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello AWS"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        ),
        (
            "responses",
            "/openai/v1/responses",
            {
                "id": "resp-1",
                "model": "native",
                "created_at": 1,
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "hello AWS"}]}
                ],
                "usage": {"input_tokens": 2, "output_tokens": 2},
            },
        ),
    ],
)
async def test_http_gateway_routes_all_bedrock_protocols(
    protocol: str,
    path: str,
    payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = "https://bedrock-runtime.us-east-1.amazonaws.com"
    cfg = {
        "gateway_auth": {"enabled": False},
        "anonymization": {"enabled": False},
        "providers": [
            {
                "name": "aws-it",
                "type": "bedrock",
                "bedrock_protocol": protocol,
                "base_url": host + ("/anthropic" if protocol == "messages" else "/openai/v1"),
                "tier": 3,
                "api_key_env": "BEDROCK_IT_KEY",
                "models": ["native"],
            }
        ],
    }
    file = tmp_path / "gateway.yaml"
    file.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(file))
    monkeypatch.setenv("BEDROCK_IT_KEY", "synthetic-integration-key")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "synthetic-ambient-key")
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LQ_AI_DATABASE_URL", raising=False)
    with respx.mock(assert_all_called=False) as router:
        upstream = router.post(host + path).mock(return_value=httpx.Response(200, json=payload))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "aws-it/native",
                    "messages": [{"role": "user", "content": "hello"}],
                    "anonymize": False,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["choices"][0]["message"]["content"] == "hello AWS"
            assert body["routed_provider"] == "aws-it"
            assert body["routed_inference_tier"] == 3
            models = (await client.get("/v1/models")).json()["data"]
            assert any(x["id"] == "aws-it/native" for x in models)
            status = (await client.get("/admin/v1/provider-keys")).json()
            assert "synthetic-integration-key" not in json.dumps(status)
            assert upstream.called
            rotated = await client.patch(
                "/admin/v1/provider-keys/aws-it", json={"api_key": "synthetic-rotated-key"}
            )
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["source"] == "runtime"
            assert "synthetic-rotated-key" not in rotated.text
            again = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "aws-it/native",
                    "messages": [{"role": "user", "content": "hello"}],
                    "anonymize": False,
                },
            )
            assert again.status_code == 200, again.text
            header = "x-api-key" if protocol == "messages" else "authorization"
            assert upstream.calls.last.request.headers[header].endswith("synthetic-rotated-key")
            revoked = await client.delete("/admin/v1/provider-keys/aws-it")
            assert revoked.status_code == 204
            denied = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "aws-it/native",
                    "messages": [{"role": "user", "content": "hello"}],
                    "anonymize": False,
                },
            )
            assert denied.status_code == 503
            models = (await client.get("/v1/models")).json()["data"]
            assert not any(x["id"] == "aws-it/native" for x in models)
            # Re-reading the persisted configuration simulates startup: a
            # revoked runtime key must not revive through an ambient AWS key.
            revoked_provider = load_config(file).provider_by_name("aws-it")
            assert revoked_provider is not None
            with pytest.raises(ValueError, match="explicit api_key_env"):
                build_adapter(revoked_provider)
