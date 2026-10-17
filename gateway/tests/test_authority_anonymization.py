"""Actual gateway/authority transport with request-local pseudonyms."""

import hashlib
import json
from dataclasses import dataclass

import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.anonymization.authority import AuthorityAnonymizationRefused, anonymize_authority_args
from app.anonymization.engine import Anonymizer
from app.api.admin import router as admin_router
from app.api.tools import router as tools_router
from app.config import GatewayConfig
from app.config_revision import REVISION_HEADER, configuration_revision
from app.main import build_tool_adapter
from app.router import Router
from app.tool_egress_log import RecordingToolEgressLogWriter


@dataclass
class Span:
    start: int
    end: int
    entity_type: str = "PERSON"
    score: float = 0.99


class Analyzer:
    def analyze(self, *, text, language="en"):
        return [Span(text.index("Alice"), text.index("Alice") + 5)] if "Alice" in text else []


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("GOVINFO_API_KEY", "fixture-key")
    monkeypatch.delenv("LQ_AI_GATEWAY_KEY", raising=False)
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    config = GatewayConfig.model_validate(
        {
            "anonymization": {"enabled": True, "apply_at_tiers": [4]},
            "tool_providers": [
                {
                    "name": "statutes",
                    "type": "govinfo",
                    "base_url": "https://api.govinfo.gov",
                    "api_key_env": "GOVINFO_API_KEY",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["api.govinfo.gov"]},
                    "anonymize_outbound": True,
                }
            ],
        }
    )
    adapter = build_tool_adapter(config.tool_providers[0])
    assert adapter is not None
    writer = RecordingToolEgressLogWriter()
    app = FastAPI()
    app.state.config = config
    app.include_router(tools_router)
    app.include_router(admin_router)
    app.state.anonymizer = Anonymizer(Analyzer())
    app.state.router = Router(
        config=config, adapters={}, tool_adapters={"statutes": adapter}, tool_egress_log=writer
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, config, writer, app
    finally:
        await adapter.aclose()


async def call(env, args, *, tool="search_authority", require=True, revision="current"):
    client, config, _, _ = env
    headers = (
        {}
        if revision is None
        else {
            REVISION_HEADER: configuration_revision(config) if revision == "current" else revision
        }
    )
    return await client.post(
        f"/v1/tools/statutes/{tool}",
        json={"args": args, "require_anonymization": require},
        headers=headers,
    )


@respx.mock
async def test_query_pseudonymized_public_evidence_verbatim(env, caplog):
    route = respx.post("https://api.govinfo.gov/search").respond(
        200,
        json={
            "results": [
                {
                    "packageId": "USCODE-2024-title15",
                    "title": "Alice and PERSON_0001 public text",
                    "collectionCode": "USCODE",
                    "dateIssued": "2024-01-01",
                }
            ]
        },
    )
    args = {"query": "Alice antitrust", "collection": "USCODE", "page_size": 5}
    response = await call(env, args)
    assert response.status_code == 200, response.text
    sent = route.calls[0].request
    assert json.loads(sent.content)["query"] == "PERSON_0001 antitrust"
    assert "require_anonymization" not in sent.content.decode()
    assert REVISION_HEADER not in sent.headers
    assert args["query"] == "Alice antitrust"
    assert response.json()["anonymization_applied"] is True
    assert response.json()["payload"]["results"][0]["title"] == "Alice and PERSON_0001 public text"
    assert env[2].rows[-1].anonymization_applied is True
    assert "Alice" not in repr(env[2].rows) + caplog.text


@respx.mock
async def test_public_retrieval_id_and_evidence_not_rewritten(env):
    route = respx.get("https://api.govinfo.gov/packages/USCODE-2024-title15/summary").respond(
        200, json={"packageId": "USCODE-2024-title15", "title": "Alice statute"}
    )
    response = await call(env, {"package_id": "USCODE-2024-title15"}, tool="get_authority")
    assert response.status_code == 200, response.text
    assert route.call_count == 1
    assert response.json()["anonymization_applied"] is True
    assert response.json()["payload"]["title"] == "Alice statute"


@pytest.mark.parametrize(
    "mutation", ["disabled", "tiers", "provider", "engine", "missing_revision", "old_revision"]
)
@respx.mock
async def test_no_raw_fallback(env, mutation, monkeypatch, caplog):
    _, config, writer, app = env
    revision = "current"
    if mutation == "disabled":
        config.anonymization.enabled = False
    elif mutation == "tiers":
        config.anonymization.apply_at_tiers = [3]
    elif mutation == "provider":
        config.tool_providers[0].anonymize_outbound = False
    elif mutation == "engine":

        def fail(*args, **kwargs):
            raise RuntimeError("PRIVATE_ENGINE_INPUT Alice")

        monkeypatch.setattr(app.state.anonymizer, "pseudonymize_into", fail)
    elif mutation == "missing_revision":
        revision = None
    else:
        revision = hashlib.sha256(
            json.dumps(
                config.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    response = await call(env, {"query": "Alice", "collection": "USCODE"}, revision=revision)
    assert response.status_code in {403, 412}
    assert not respx.calls
    assert "Alice" not in response.text + repr(writer.rows) + caplog.text
    if mutation in {"disabled", "tiers", "engine"}:
        assert writer.rows[-1].refused is True


@pytest.mark.parametrize(
    "tool,args",
    [
        (
            "search_authority",
            {"query": "Alice", "collection": "USCODE", "private": {"Alice": "secret"}},
        ),
        ("search_authority", {"query": ["Alice"], "collection": "USCODE"}),
        ("search_authority", {"query": "x" * 8193, "collection": "USCODE"}),
        ("search_authority", {"query": "Alice", "collection": "Alice"}),
        ("search_authority", {"query": "Alice", "collection": "USCODE", "page_size": True}),
        ("get_authority", {"package_id": "Alice"}),
        ("get_authority", {"package_id": "../Alice?private=true"}),
        ("get_authority", {"package_id": "USCODE-2024-title15", "granule_id": "other"}),
        ("unsupported", {}),
    ],
)
@respx.mock
async def test_unreviewed_arguments_refuse(env, tool, args):
    response = await call(env, args, tool=tool)
    assert response.status_code == 403
    assert not respx.calls
    assert env[2].rows[-1].refused is True


@respx.mock
async def test_legacy_call_unchanged(env):
    route = respx.post("https://api.govinfo.gov/search").respond(200, json={"results": []})
    response = await call(
        env, {"query": "Alice", "collection": "USCODE"}, require=False, revision=None
    )
    assert response.status_code == 200
    assert json.loads(route.calls[0].request.content)["query"] == "Alice"
    assert response.json()["anonymization_applied"] is False
    assert env[2].rows[-1].anonymization_applied is False


@pytest.mark.parametrize(
    "provider,tool,args",
    [
        ("edgar", "search_authority", {"query": "Alice liability", "forms": "10-K,8-K"}),
        ("edgar", "get_authority", {"external_ref": "123_00001234_annual.htm"}),
        ("eurlex", "get_authority", {"external_ref": "32016R0679"}),
    ],
)
def test_other_authority_shapes(provider, tool, args):
    result = anonymize_authority_args(provider, tool, args, anonymizer=Anonymizer(Analyzer()))
    assert result == {**args, **({"query": "PERSON_0001 liability"} if "query" in args else {})}


@pytest.mark.parametrize(
    "provider,tool,args",
    [
        ("mcp", "search_authority", {"query": "Alice"}),
        ("eurlex", "search_authority", {"query": "Alice"}),
        ("edgar", "get_authority", {"external_ref": "123_00001234_Alice.htm"}),
        ("eurlex", "get_authority", {"external_ref": "32016R0679/Alice"}),
    ],
)
def test_unsupported_or_sensitive_references(provider, tool, args):
    with pytest.raises(AuthorityAnonymizationRefused):
        anonymize_authority_args(provider, tool, args, anonymizer=Anonymizer(Analyzer()))


def test_real_engine_query_contact_data():
    result = anonymize_authority_args(
        "govinfo",
        "search_authority",
        {
            "collection": "CFR",
            "query": "contact counsel@example.com about antitrust",
        },
        anonymizer=Anonymizer(),
    )
    assert "counsel@example.com" not in result["query"]
    assert "EMAIL_" in result["query"]


async def test_admin_advertises_checked_authority_capability(env):
    response = await env[0].get("/admin/v1/config")
    assert response.status_code == 200
    assert response.json()["authority_anonymization_version"] == 1
    assert response.json()["configuration_revision"] == configuration_revision(env[1])


@pytest.mark.parametrize(
    "provider,args,allowed",
    [
        ("govinfo", {"package_id": "USCODE-2024-title15"}, True),
        ("edgar", {"external_ref": "320193_000032019324000123_aapl-20240928.htm"}, False),
        ("eurlex", {"external_ref": "32016R0679"}, True),
    ],
)
def test_real_engine_reference_ambiguity_never_changes_document_id(provider, args, allowed):
    if allowed:
        assert (
            anonymize_authority_args(provider, "get_authority", args, anonymizer=Anonymizer())
            == args
        )
    else:
        with pytest.raises(AuthorityAnonymizationRefused):
            anonymize_authority_args(provider, "get_authority", args, anonymizer=Anonymizer())
