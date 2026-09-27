"""Model-profile acceptance: real Postgres, guard, worker and checkpoint paths.

The provider is controlled here. An unmocked provider run is a separate UAT gate.
"""

import asyncio
import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.dependencies import get_active_user
from app.api.orchestration import service
from app.autonomous.orchestration.chat_demo import contract_qa_outcome
from app.autonomous.orchestration.service import DemonstrationService, ModelDemoGateway
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.orchestration import OrchestrationAdmission
from app.models.user import User
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.workers.orchestration_worker import orchestration_session_job, orchestration_watchdog

BASE = "/api/v1/autonomous/orchestration"


@pytest.mark.unit
async def test_disabled_chat_worker_does_no_database_or_queue_work():
    assert await orchestration_session_job({}, str(uuid4()), str(uuid4())) == {"status": "disabled"}
    assert await orchestration_watchdog({}) == {"status": "disabled"}
    disabled = SimpleNamespace(settings=SimpleNamespace(orchestration_chat_enabled=False))
    assert await orchestration_watchdog({"orchestration_runtime": disabled}) == {
        "status": "disabled"
    }


class ModelGateway:
    def __init__(self):
        self.config = {
            "configuration_revision": "b" * 64,
            "providers": [
                {
                    "name": "selected",
                    "type": "openai",
                    "tier": 1,
                    "enabled": True,
                    "base_url": "https://fixture.invalid",
                }
            ],
            "model_aliases": {},
            "inference_tiers": {"overrides": {}, "defaults": {}},
            "cost_tracking": {
                "enabled": True,
                "rates": {"selected/native": {"input_per_mtok": "2", "output_per_mtok": "6"}},
            },
            "anonymization": {"enabled": True, "apply_at_tiers": [1]},
        }
        self.requests = []
        self.operations = []
        self.proposal = json.dumps(
            {
                "tasks": [
                    {
                        "topic": topic,
                        "question": question,
                        "boundaries": "Only the fictional agreement",
                        "output_contract": "A clause-based answer",
                        "stopping_condition": "One answer",
                    }
                    for topic, question in (
                        ("Payments", "What must Customer pay and when?"),
                        (
                            "Renewal and termination",
                            "How can Customer prevent renewal or terminate?",
                        ),
                    )
                ]
            }
        )
        self.child_gate = asyncio.Event()
        self.child_gate.set()
        self.two_entered = asyncio.Event()
        self.active = self.peak = 0
        self.uncertain = False
        self.synthesis_finish_reason = "stop"

    async def get_admin_config(self):
        return deepcopy(self.config)

    async def chat_completion(self, request, *, configuration_revision):
        assert configuration_revision == self.config["configuration_revision"]
        self.requests.append(request)
        payload = json.loads(request.messages[1].content)
        operation = payload["inputs"]["operation"]
        self.operations.append(operation)
        if self.uncertain:
            raise TimeoutError("private provider details must not escape")
        if operation == "propose_plan":
            content = self.proposal
        elif operation == "answer_contract_question":
            assert "# Contract QA" in request.messages[0].content
            assert "Supporting file: reference/" in request.messages[0].content
            assert "§5 Term and renewal" in payload["inputs"]["document"]
            assert payload["inputs"]["question"] == payload["task"]["question"]
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= 2:
                self.two_entered.set()
            try:
                await self.child_gate.wait()
                assert (
                    "Return only the Contract QA answer as Markdown"
                    in payload["inputs"]["response_contract"]
                )
                content = (
                    "Customer can prevent renewal with written notice at least 30 days "
                    "before the current term ends. [§5]\n\n"
                    '> "at least 30 days before the current term ends." [§5]'
                )
            finally:
                self.active -= 1
        else:
            assert operation == "synthesize_answers"
            assert len(payload["inputs"]["topics"]) == 2
            assert all("[§5]" in t["outcome"]["findings"][0] for t in payload["inputs"]["topics"])
            content = "Model-generated from fictional inputs; unverified.\nRenewal requires 30 days' notice [§5]."
        return SimpleNamespace(
            routed_provider="selected",
            routed_model="native",
            routed_inference_tier=1,
            anonymization_applied=True,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason=self.synthesis_finish_reason
                    if operation == "synthesize_answers"
                    else "stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=30),
        )


@pytest_asyncio.fixture
async def model_demo(env, test_db_url, monkeypatch):
    skills = MutableSkillRegistry(load_registry(Path(__file__).resolve().parents[4] / "skills"))
    settings = get_settings().model_copy(
        update={
            "database_url": test_db_url,
            "orchestration_chat_enabled": True,
            "orchestration_chat_project_id": str(env.project_id),
            "orchestration_chat_provider": "selected",
            "orchestration_chat_model": "native",
            "orchestration_chat_minimum_tier": 1,
            "orchestration_chat_budget_usd": Decimal("2.0000"),
            "orchestration_deployment_children": 2,
        }
    )
    gateway = ModelGateway()
    runtime = DemonstrationService(settings, skills, env.factory, gateway=gateway)
    await runtime.for_profile("model_demo_v1").executor().checkpoints.setup()
    async with env.factory() as db:
        user = await db.get(User, env.owner_id)
    queued = []

    async def enqueue(root_id, session_id):
        queued.append((root_id, session_id))
        return True

    monkeypatch.setattr("app.api.orchestration.enqueue_orchestration_job", enqueue)
    monkeypatch.setattr("app.workers.orchestration_worker.enqueue_orchestration_job", enqueue)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_active_user] = lambda: user
    app.dependency_overrides[service] = lambda: runtime
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(
                client=client,
                runtime=runtime,
                env=env,
                gateway=gateway,
                ctx={"orchestration_runtime": runtime},
                queued=queued,
                user=user,
            )
    finally:
        gateway.child_gate.set()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


async def start(api):
    response = await api.client.post(
        f"{BASE}/chat-runs",
        json={
            "request_id": str(uuid4()),
            "project_id": str(api.env.project_id),
            "goal": "Explain payment, renewal and termination questions independently.",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


async def read(api, root_id):
    response = await api.client.get(f"{BASE}/chat-runs/{root_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def plan(api):
    initial = await start(api)
    root_id = initial["root_id"]
    result = await orchestration_session_job(api.ctx, root_id, root_id)
    assert result["status"] == "completed", result
    return await read(api, root_id)


async def approve(api, value):
    tree = value["tree"]
    response = await api.client.post(
        f"{BASE}/{value['root_id']}/approve",
        json={
            "revision": tree["plan"]["revision"],
            "plan_hash": tree["plan_hash"],
        },
    )
    assert response.status_code == 200, response.text


async def test_complete_skill_backed_run_through_worker_and_receipts(model_demo):
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


async def test_retained_run_includes_only_its_pinned_agreement(model_demo, monkeypatch):
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


def test_contract_qa_adaptive_markdown_is_retained_without_repair():
    answer = (
        "The Supplier provides two onboarding sessions within 20 business days. [§3]\n\n"
        "### Support\nThe Supplier acknowledges requests within two business days. [§4]"
    )
    outcome = contract_qa_outcome(answer, "stop")
    assert outcome.status == "completed"
    assert outcome.findings == (answer,)
    assert outcome.summary.startswith("The Supplier provides")
    assert outcome.verification == "unverified" and outcome.artifact is None


def test_contract_qa_malformed_json_and_incomplete_answers_still_fail():
    for content, reason in (
        ('```json\n{"status":"completed","findings":[ way]}\n```', "stop"),
        ("A valid-looking answer [§4]", "length"),
        (" ", "stop"),
        ("A" * 4097, "stop"),
        ("Answer\x00[§4]", "stop"),
    ):
        with pytest.raises((ValueError, TypeError)):
            contract_qa_outcome(content, reason)


def test_contract_qa_completed_json_effect_remains_readable():
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
async def test_invalid_model_plan_retains_charge_without_fallback(model_demo, proposal):
    api = model_demo
    api.gateway.proposal = proposal
    value = await plan(api)
    assert value["status"] == "failed" and value["stop_reason"] == "invalid_proposal"
    assert value["tree"] is None and value["spent_usd"] != "0.0000"
    assert api.gateway.operations == ["propose_plan"]


async def test_halt_before_planning_and_disable_preserve_read_access(model_demo):
    api = model_demo
    value = await start(api)
    root = value["root_id"]
    api.runtime.settings.orchestration_chat_enabled = False
    assert (await api.client.get(f"{BASE}/chat-runs")).json() == {"enabled": False}
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "disabled"}
    assert (await api.client.post(f"{BASE}/chat-runs/{root}/halt")).json()["status"] == "halted"
    assert (await read(api, root))["status"] == "halted"
    assert not api.gateway.requests


async def test_changed_gateway_configuration_cannot_dispatch_children(model_demo):
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


async def test_uncertain_planning_is_retained_without_automatic_retry(model_demo):
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


async def test_request_idempotency_and_rejection(model_demo):
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


async def test_wrong_hash_cannot_approve_or_admit_children(model_demo):
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


async def test_watchdog_requeues_approved_root_after_lost_wakeup(model_demo):
    api = model_demo
    value = await plan(api)
    await approve(api, value)
    api.queued.clear()
    result = await orchestration_watchdog(api.ctx)
    assert result["woken"] == 1
    assert (UUID(value["root_id"]), UUID(value["root_id"])) in api.queued
    assert (await read(api, value["root_id"]))["status"] == "queued"


async def test_watchdog_requeues_admitted_children_after_lost_wakeup(model_demo):
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
    model_demo, monkeypatch
):
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

    async def db_override():
        async with api.env.factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr("app.api.orchestration.service", lambda request: api.runtime)
    halted = await api.client.post(f"/api/v1/autonomous/sessions/{child_id}/halt")
    assert halted.status_code == 200 and halted.json()["status"] == "halted"
    assert (await read(api, root))["status"] == "halted"


async def test_one_json_presentation_fence_preserves_strict_plan_validation(model_demo):
    api = model_demo
    api.gateway.proposal = "```json\n" + api.gateway.proposal + "\n```"
    value = await plan(api)
    assert value["status"] == "awaiting_approval"
    assert len(value["tree"]["plan"]["children"]) == 2
    assert api.gateway.operations == ["propose_plan"]


async def test_scope_and_pricing_refusals_before_planning(model_demo):
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
async def test_model_transport_uses_bounded_timeout_and_closes(monkeypatch, fail):
    """Regression for live UAT's 60-second ordinary-chat timeout mismatch."""
    created = []

    class Transport:
        def __init__(self, url, key, *, timeout):
            self.timeout, self.closed = timeout, False
            created.append(self)

        async def chat_completion(self, request, *, configuration_revision):
            assert configuration_revision == "a" * 64
            if fail:
                raise TimeoutError
            return "response"

        async def aclose(self):
            self.closed = True

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


async def test_planning_is_not_approvable_and_cross_owner_cannot_inspect(model_demo):
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


async def test_truncated_synthesis_fails_without_replaying_and_retains_children(model_demo):
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
