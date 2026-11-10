"""Model-profile acceptance: real Postgres, guard, worker and checkpoint paths.

The provider is controlled here. An unmocked provider run is a separate UAT gate.
"""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.autonomous.orchestration.model_harness import BASE, approve, plan, read, start

from app.autonomous.orchestration.chat_demo import contract_qa_outcome
from app.autonomous.orchestration.service import DemonstrationService, ModelDemoGateway
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.orchestration import OrchestrationAdmission
from app.workers.orchestration_worker import orchestration_session_job, orchestration_watchdog


@pytest.mark.unit
async def test_disabled_chat_worker_does_no_database_or_queue_work() -> None:
    assert await orchestration_session_job({}, str(uuid4()), str(uuid4())) == {"status": "disabled"}
    assert await orchestration_watchdog({}) == {"status": "disabled"}
    disabled = SimpleNamespace(settings=SimpleNamespace(orchestration_chat_enabled=False))
    assert await orchestration_watchdog({"orchestration_runtime": disabled}) == {
        "status": "disabled"
    }


async def test_complete_skill_backed_run_through_worker_and_receipts(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    caps = await api.client.get(f"{BASE}/chat-runs")
    assert caps.status_code == 200 and caps.json()["planning_allowance_usd"] != "0"
    assert not api.gateway.requests
    value = await start(api)
    root = value["root_id"]
    assert value["status"] == "planning" and value["tree"] is None
    assert not api.gateway.requests
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "completed"}
    value = await read(api, root)
    assert value["status"] == "awaiting_approval"
    assert value["effects"][0]["skill"]["name"] == "orchestration-chat-demo"
    assert value["spent_usd"] != "0.0000"
    async with api.env.factory() as db:
        assert not await db.scalar(select(OrchestrationAdmission.session_id))
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "stopped"}
    assert api.gateway.operations == ["propose_plan"]
    await approve(api, value)
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "waiting_children"}
    children = value["tree"]["plan"]["children"]
    api.gateway.child_gate.clear()
    jobs = [
        asyncio.create_task(orchestration_session_job(api.ctx, root, c["dispatch_id"]))
        for c in children
    ]
    try:
        await asyncio.wait_for(api.gateway.two_entered.wait(), 8)
        assert api.gateway.peak == 2
    finally:
        api.gateway.child_gate.set()
        results = await asyncio.gather(*jobs)
    assert all(r["status"] == "completed" for r in results)
    # A fresh service/executor resumes the same durable root join.
    api.ctx["orchestration_runtime"] = DemonstrationService(
        api.runtime.settings, api.runtime.skills, api.env.factory, gateway=api.gateway
    )
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "completed"}
    final = await read(api, root)
    assert final["status"] == "completed" and final["tree"]["result"]["coverage"] == "complete"
    assert api.gateway.operations.count("propose_plan") == 1
    assert api.gateway.operations.count("synthesize_answers") == 1
    for child in final["tree"]["children"]:
        skill_receipt = next(e for e in child["effects"] if e["intent"] == "run_skill")
        assert skill_receipt["skill"]["name"] == "contract-qa"
        assert skill_receipt["skill"]["version"] == "1.0.0"
        assert len(skill_receipt["skill"]["digest"]) == 64
        assert skill_receipt["accounting"]["provider"] == "selected"
        assert child["outcome"]["artifact"] and "[§5]" in child["outcome"]["findings"][0]
        # ADR 0038 D4: the child read the agreement through its granted tool.
        assert [t["name"] for t in child["tools"]] == ["read_document", "read_note", "save_note"]
        read_step = next(e for e in child["effects"] if e["effect_key"] == "topic:t1:c0")
        assert read_step["intent"] == "retrieve_chunks" and read_step["status"] == "completed"
        assert read_step["step"]["kind"] == "document_read"
        assert read_step["step"]["label"] == "Read a selected document"
        assert read_step["step"]["reason"] == "The agreement is needed."
        assert read_step["step"]["summary"]["document"] == 1
        assert read_step["step"]["summary"]["truncated"] is False
        assert "text" not in read_step["step"]["summary"]
    assert any("§5 Term and renewal" in result for result in api.gateway.tool_results)
    assert len(api.gateway.synthesis_topics) == 2
    assert all("[§5]" in t["outcome"]["findings"][0] for t in api.gateway.synthesis_topics)
    # A run with no chat sends no chat correlation, and a truthful purpose.
    assert {c[2] for c in api.gateway.correlations} == {"orchestration_run"}
    assert all(c[0] is None and c[1] is None for c in api.gateway.correlations)
    assert final["chat_id"] is None and final["profile"] == "model_demo_v1"
    assert final["tree"]["plan"]["contract_version"] == 3
    assert final["tree"]["plan"]["documents"][0]["filename"] == "fictional-vendor-agreement.md"


async def test_retained_run_includes_only_its_pinned_agreement(
    model_demo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = model_demo
    value = await start(api)
    source = value["packet"]
    assert (
        source and hashlib.sha256(source.encode()).hexdigest() == value["planning"]["packet_digest"]
    )
    api.runtime.settings.orchestration_chat_enabled = False
    assert (await read(api, value["root_id"]))["packet"] == source
    monkeypatch.setattr("app.api.orchestration.packet", lambda _: "A changed agreement")
    assert (await read(api, value["root_id"]))["packet"] is None


def test_contract_qa_adaptive_markdown_is_retained_without_repair() -> None:
    answer = (
        "The Supplier provides two onboarding sessions within 20 business days. [§3]\n\n"
        "### Support\nThe Supplier acknowledges requests within two business days. [§4]"
    )
    outcome = contract_qa_outcome(answer, "stop")
    assert outcome.status == "completed"
    assert outcome.findings == (answer,)
    assert outcome.summary.startswith("The Supplier provides")
    assert outcome.verification == "unverified" and outcome.artifact is None


def test_contract_qa_malformed_json_and_incomplete_answers_still_fail() -> None:
    for content, reason in (
        ('```json\n{"status":"completed","findings":[ way]}\n```', "stop"),
        ("A valid-looking answer [§4]", "length"),
        (" ", "stop"),
        ("A" * 4097, "stop"),
        ("Answer\x00[§4]", "stop"),
    ):
        with pytest.raises((ValueError, TypeError)):
            contract_qa_outcome(content, reason)


def test_contract_qa_completed_json_effect_remains_readable() -> None:
    content = json.dumps(
        {
            "status": "completed",
            "summary": "The agreement answers this question.",
            "findings": ["Customer can prevent renewal with notice. [§5]"],
            "verification": "unverified",
            "failure_code": None,
        }
    )
    outcome = contract_qa_outcome(content, "stop")
    assert outcome.status == "completed" and outcome.findings[0].endswith("[§5]")


@pytest.mark.parametrize(
    "proposal",
    [
        "not json",
        '{"tasks":[]}',
        '{"tasks":[],"grants":["notify"]}',
        'Proposed plan:\n```json\n{"tasks":[]}\n```',
        '```json\n{"tasks":[],"grants":["notify"]}\n```',
    ],
)
async def test_invalid_model_plan_retains_charge_without_fallback(
    model_demo: SimpleNamespace, proposal: str
) -> None:
    api = model_demo
    api.gateway.proposal = proposal
    value = await plan(api)
    assert value["status"] == "failed" and value["stop_reason"] == "invalid_proposal"
    assert value["tree"] is None and value["spent_usd"] != "0.0000"
    assert api.gateway.operations == ["propose_plan"]


async def test_halt_before_planning_and_disable_preserve_read_access(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await start(api)
    root = value["root_id"]
    api.runtime.settings.orchestration_chat_enabled = False
    assert (await api.client.get(f"{BASE}/chat-runs")).json() == {"enabled": False}
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "disabled"}
    assert (await api.client.post(f"{BASE}/chat-runs/{root}/halt")).json()["status"] == "halted"
    assert (await read(api, root))["status"] == "halted"
    assert not api.gateway.requests


async def test_changed_gateway_configuration_cannot_dispatch_children(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await plan(api)
    await approve(api, value)
    root = value["root_id"]
    await orchestration_session_job(api.ctx, root, root)
    api.gateway.config["configuration_revision"] = "c" * 64
    for child in value["tree"]["plan"]["children"]:
        assert await orchestration_session_job(api.ctx, root, child["dispatch_id"]) == {
            "status": "stopped"
        }
    assert api.gateway.operations == ["propose_plan"]


async def test_uncertain_planning_is_retained_without_automatic_retry(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.uncertain = True
    value = await start(api)
    root = value["root_id"]
    await orchestration_session_job(api.ctx, root, root)
    result = await read(api, root)
    assert result["status"] == "uncertain" and result["reserved_usd"] != "0.0000"
    assert result["effects"][0]["status"] == "uncertain"
    assert "private provider details must not escape" not in json.dumps(result)
    await orchestration_session_job(api.ctx, root, root)
    assert len(api.gateway.requests) == 1


async def test_request_idempotency_and_rejection(model_demo: SimpleNamespace) -> None:
    api = model_demo
    value = await plan(api)
    response = await api.client.post(
        f"{BASE}/chat-runs",
        json={
            "request_id": value["root_id"],
            "project_id": str(api.env.project_id),
            "goal": value["planning"]["goal"],
        },
    )
    assert response.status_code == 202 and response.json()["root_id"] == value["root_id"]
    response = await api.client.post(f"{BASE}/{value['root_id']}/reject", json={"revision": 1})
    assert response.status_code == 200
    final = await read(api, value["root_id"])
    assert final["status"] == "rejected" and final["spent_usd"] == value["spent_usd"]
    assert api.gateway.operations == ["propose_plan"]
    assert (await start(api))["status"] == "planning"


async def test_wrong_hash_cannot_approve_or_admit_children(model_demo: SimpleNamespace) -> None:
    api = model_demo
    value = await plan(api)
    root = value["root_id"]
    response = await api.client.post(
        f"{BASE}/{root}/approve", json={"revision": 1, "plan_hash": "0" * 64}
    )
    assert response.status_code == 409
    assert (await read(api, root))["status"] == "awaiting_approval"
    async with api.env.factory() as db:
        assert not await db.scalar(select(OrchestrationAdmission.session_id))
    assert api.gateway.operations == ["propose_plan"]


async def test_watchdog_requeues_approved_root_after_lost_wakeup(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await plan(api)
    await approve(api, value)
    api.queued.clear()
    result = await orchestration_watchdog(api.ctx)
    assert result["woken"] == 1
    assert (UUID(value["root_id"]), UUID(value["root_id"])) in api.queued
    assert (await read(api, value["root_id"]))["status"] == "queued"


async def test_watchdog_requeues_admitted_children_after_lost_wakeup(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await plan(api)
    await approve(api, value)
    root = value["root_id"]
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "waiting_children"}
    children = (await read(api, root))["tree"]["children"]
    child_ids = {UUID(child["session_id"]) for child in children}
    assert len(child_ids) == 2

    # Lose the notifications emitted when the root admitted its children.
    api.queued.clear()
    result = await orchestration_watchdog(api.ctx)
    assert result["woken"] == len(child_ids) + 1
    assert {(UUID(root), child_id) for child_id in child_ids} <= set(api.queued)
    assert (await read(api, root))["status"] == "waiting_children"

    # A recovered notification still drives the admitted child through the worker.
    child_id = next(iter(child_ids))
    assert await orchestration_session_job(api.ctx, root, str(child_id)) == {"status": "completed"}


async def test_legacy_worker_refuses_chat_child_and_legacy_halt_reaches_tree(
    model_demo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import autonomous_worker

    api = model_demo
    value = await plan(api)
    await approve(api, value)
    root = value["root_id"]
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "waiting_children"}
    child_id = (await read(api, root))["tree"]["children"][0]["session_id"]
    monkeypatch.setattr(autonomous_worker, "get_session_factory", lambda: api.env.factory)
    monkeypatch.setattr(autonomous_worker, "_gateway_from_ctx", lambda ctx: None)
    blocked = await autonomous_worker.autonomous_session_job({}, child_id)
    assert blocked["status"] == "governed_orchestration_only"

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with api.env.factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr("app.api.orchestration.service", lambda request: api.runtime)
    halted = await api.client.post(f"/api/v1/autonomous/sessions/{child_id}/halt")
    assert halted.status_code == 200 and halted.json()["status"] == "halted"
    assert (await read(api, root))["status"] == "halted"


async def test_one_json_presentation_fence_preserves_strict_plan_validation(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.proposal = "```json\n" + api.gateway.proposal + "\n```"
    value = await plan(api)
    assert value["status"] == "awaiting_approval"
    assert len(value["tree"]["plan"]["children"]) == 2
    assert api.gateway.operations == ["propose_plan"]


async def test_scope_and_pricing_refusals_before_planning(model_demo: SimpleNamespace) -> None:
    api = model_demo
    wrong_project = await api.client.post(
        f"{BASE}/chat-runs",
        json={"request_id": str(uuid4()), "project_id": str(uuid4()), "goal": "Question"},
    )
    assert wrong_project.status_code == 404
    api.gateway.config["cost_tracking"]["rates"] = {}
    response = await api.client.post(
        f"{BASE}/chat-runs",
        json={
            "request_id": str(uuid4()),
            "project_id": str(api.env.project_id),
            "goal": "Question",
        },
    )
    assert response.status_code == 403 and not api.gateway.requests


@pytest.mark.parametrize("fail", [False, True])
async def test_model_transport_uses_bounded_timeout_and_closes(
    monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    """Regression for live UAT's 60-second ordinary-chat timeout mismatch."""

    class Transport:
        def __init__(self, url: str, key: str, *, timeout: float) -> None:
            self.timeout, self.closed = timeout, False
            created.append(self)

        async def chat_completion(self, request: Any, *, configuration_revision: str) -> str:
            assert configuration_revision == "a" * 64
            if fail:
                raise TimeoutError
            return "response"

        async def aclose(self) -> None:
            self.closed = True

    created: list[Transport] = []
    monkeypatch.setattr("app.autonomous.orchestration.service.GatewayClient", Transport)
    settings = get_settings().model_copy(update={"orchestration_chat_timeout_seconds": 300})
    gateway = ModelDemoGateway(settings)
    if fail:
        with pytest.raises(TimeoutError):
            await gateway.chat_completion(object(), configuration_revision="a" * 64)
    else:
        assert (
            await gateway.chat_completion(object(), configuration_revision="a" * 64) == "response"
        )
    assert created[0].timeout == 300 and created[0].closed


async def test_planning_is_not_approvable_and_cross_owner_cannot_inspect(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await start(api)
    root = value["root_id"]
    premature = await api.client.post(
        f"{BASE}/{root}/approve", json={"revision": 1, "plan_hash": "a" * 64}
    )
    assert premature.status_code == 409
    api.user.id = uuid4()
    assert (await api.client.get(f"{BASE}/chat-runs/{root}")).status_code == 404
    assert (await api.client.post(f"{BASE}/chat-runs/{root}/halt")).status_code == 404
    assert not api.gateway.requests


async def test_truncated_synthesis_fails_without_replaying_and_retains_children(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await plan(api)
    await approve(api, value)
    root = value["root_id"]
    await orchestration_session_job(api.ctx, root, root)
    for child in value["tree"]["plan"]["children"]:
        await orchestration_session_job(api.ctx, root, child["dispatch_id"])
    api.gateway.synthesis_finish_reason = "length"
    await orchestration_session_job(api.ctx, root, root)
    final = await read(api, root)
    assert final["status"] == "failed" and final["stop_reason"] == "invalid_synthesis"
    assert final["tree"]["result"] is None and final["tree"]["partial_summary"]
    assert all(c["outcome"]["status"] == "completed" for c in final["tree"]["children"])
    await orchestration_session_job(api.ctx, root, root)
    assert api.gateway.operations.count("synthesize_answers") == 1
