"""Controlled provider and API fixture for model-backed run profiles.

Real Postgres, guard, worker and checkpoint paths; only the provider is
controlled. An unmocked provider run is a separate UAT gate.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_active_user
from app.api.orchestration import service
from app.autonomous.orchestration.service import DemonstrationService
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat
from app.models.user import User
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.workers.orchestration_worker import orchestration_session_job

BASE = "/api/v1/autonomous/orchestration"
CHATS = "/api/v1/chats"
PACKET_DOCUMENTS = [{"number": 1, "filename": "fictional-vendor-agreement.md"}]


def tool_call(name: str, arguments: dict[str, Any] | str, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


class ModelGateway:
    """A provider double that speaks the run's three operations.

    ``child_script`` decides what an approved child's model does on each turn:
    a list of tool calls to request, or None to answer. The default reads
    document 1 once and then answers.
    """

    def __init__(self) -> None:
        self.config: dict[str, Any] = {
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
        self.requests: list[Any] = []
        self.operations: list[str] = []
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
        self.uncertain_operations: set[str] = set()
        self.synthesis_finish_reason = "stop"
        self.expected_documents: list[dict[str, Any]] = PACKET_DOCUMENTS
        self.child_answer = (
            "Customer can prevent renewal with written notice at least 30 days "
            "before the current term ends. [§5]\n\n"
            '> "at least 30 days before the current term ends." [§5]'
        )
        self.synthesis_answer = (
            "Model-generated from fictional inputs; unverified.\n"
            "Renewal requires 30 days' notice [§5]."
        )
        self.child_script: list[list[dict[str, Any]] | None] = [
            [tool_call("read_document", {"document": 1, "reason": "The agreement is needed."})],
            None,
        ]
        # Called with the turn number at the start of each child model turn.
        self.on_child_turn: Any = None
        self.tool_results: list[str] = []
        self.child_turns: list[dict[str, Any]] = []
        self.correlations: list[tuple[str | None, str | None, str | None]] = []
        self.synthesis_topics: list[dict[str, Any]] = []
        self.plan_inputs: list[dict[str, Any]] = []

    async def get_admin_config(self) -> dict[str, Any]:
        return deepcopy(self.config)

    async def chat_completion(
        self, request: Any, *, configuration_revision: str
    ) -> SimpleNamespace:
        assert configuration_revision == self.config["configuration_revision"]
        self.requests.append(request)
        self.correlations.append(
            (request.lq_ai_chat_id, request.lq_ai_message_id, request.lq_ai_purpose)
        )
        payload = json.loads(request.messages[1].content)
        operation = payload["inputs"]["operation"]
        self.operations.append(operation)
        if self.uncertain or operation in self.uncertain_operations:
            raise TimeoutError("private provider details must not escape")
        tool_calls = None
        if operation == "propose_plan":
            self.plan_inputs.append(payload["inputs"])
            content = self.proposal
        elif operation == "answer_contract_question":
            assert "# Contract QA" in request.messages[0].content
            assert "Supporting file: reference/" in request.messages[0].content
            # The documents are not in the prompt: a child reads them with a tool.
            assert "document" not in payload["inputs"]
            assert payload["inputs"]["documents"] == self.expected_documents
            assert payload["inputs"]["question"] == payload["task"]["question"]
            results = [m.content for m in request.messages if m.role == "tool"]
            turn = sum(1 for m in request.messages if m.role == "assistant") + 1
            self.child_turns.append(
                {
                    "turn": turn,
                    "offered": [t["function"]["name"] for t in request.tools or []],
                    "results": results,
                    "last_user": [m.content for m in request.messages if m.role == "user"][-1],
                }
            )
            if self.on_child_turn is not None:
                await self.on_child_turn(turn)
            script = self.child_script
            step = script[min(turn, len(script)) - 1] if script else None
            if request.tools and step:
                content, tool_calls = "", step
            else:
                for result in results:
                    if result not in self.tool_results:
                        self.tool_results.append(result)
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
                    content = self.child_answer
                finally:
                    self.active -= 1
        else:
            assert operation == "synthesize_answers"
            self.synthesis_topics = payload["inputs"]["topics"]
            content = self.synthesis_answer
        return SimpleNamespace(
            routed_provider="selected",
            routed_model="native",
            routed_inference_tier=1,
            anonymization_applied=True,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, tool_calls=tool_calls),
                    finish_reason="tool_calls"
                    if tool_calls
                    else self.synthesis_finish_reason
                    if operation == "synthesize_answers"
                    else "stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=30),
        )


@pytest_asyncio.fixture
async def model_demo(
    env: SimpleNamespace, test_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[SimpleNamespace]:
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
            # The real-document profile stays off unless a test turns it on.
            "orchestration_documents_enabled": False,
            "orchestration_documents_provider": "selected",
            "orchestration_documents_model": "native",
            "orchestration_documents_minimum_tier": 1,
            "orchestration_documents_budget_usd": Decimal("10.0000"),
        }
    )
    gateway = ModelGateway()
    runtime = DemonstrationService(settings, skills, env.factory, gateway=gateway)
    await runtime.for_profile("model_demo_v1").executor().checkpoints.setup()
    async with env.factory() as db:
        user = await db.get(User, env.owner_id)
    queued: list[tuple[UUID, UUID]] = []
    stored: dict[str, bytes] = {}

    async def enqueue(root_id: UUID, session_id: UUID) -> bool:
        queued.append((root_id, session_id))
        return True

    async def upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        stored[storage_path] = body

    monkeypatch.setattr("app.api.orchestration.enqueue_orchestration_job", enqueue)
    monkeypatch.setattr("app.workers.orchestration_worker.enqueue_orchestration_job", enqueue)
    # The fictional agreement is filed in the demo project as a real file.
    monkeypatch.setattr("app.autonomous.orchestration.intake.upload_bytes", upload)

    async def database() -> AsyncIterator[AsyncSession]:
        async with env.factory() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_active_user] = lambda: user
    app.dependency_overrides[service] = lambda: runtime
    # Chat routes (messages, receipts, export) read this test's database.
    app.dependency_overrides[get_db] = database
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
                stored=stored,
                skills=skills,
            )
    finally:
        gateway.child_gate.set()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


async def start(api: SimpleNamespace) -> dict[str, Any]:
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


async def read(api: SimpleNamespace, root_id: str) -> dict[str, Any]:
    response = await api.client.get(f"{BASE}/chat-runs/{root_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def plan(api: SimpleNamespace) -> dict[str, Any]:
    initial = await start(api)
    root_id = initial["root_id"]
    result = await orchestration_session_job(api.ctx, root_id, root_id)
    assert result["status"] == "completed", result
    return await read(api, root_id)


async def approve(api: SimpleNamespace, value: dict[str, Any]) -> None:
    tree = value["tree"]
    response = await api.client.post(
        f"{BASE}/{value['root_id']}/approve",
        json={
            "revision": tree["plan"]["revision"],
            "plan_hash": tree["plan_hash"],
        },
    )
    assert response.status_code == 200, response.text


# --- Runs hosted in a chat (ADR 0038 D1) -------------------------------------


async def new_chat(
    api: SimpleNamespace, *, in_project: bool = True, title: str = "New chat"
) -> UUID:
    async with api.env.factory.begin() as db:
        chat = Chat(
            owner_id=api.env.owner_id,
            project_id=api.env.project_id if in_project else None,
            title=title,
        )
        db.add(chat)
        await db.flush()
        return chat.id


GOAL = "Explain payment, renewal and termination questions independently."


async def start_in_chat(
    api: SimpleNamespace,
    chat_id: UUID,
    *,
    profile: str = "model_demo_v1",
    goal: str = GOAL,
    request_id: str | None = None,
    file_ids: list[str] | None = None,
    expect: int = 202,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_id": request_id or str(uuid4()),
        "profile": profile,
        "goal": goal,
    }
    if file_ids is not None:
        body["file_ids"] = file_ids
    response = await api.client.post(f"{CHATS}/{chat_id}/runs", json=body)
    assert response.status_code == expect, response.text
    return response.json()


async def job(api: SimpleNamespace, root_id: str, session_id: str | None = None) -> str:
    result = await orchestration_session_job(api.ctx, root_id, session_id or root_id)
    return result["status"]


async def run_to_completion(api: SimpleNamespace, value: dict[str, Any]) -> dict[str, Any]:
    """Plan, approve, run every child and deliver. Returns the final read."""
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    assert planned["status"] == "awaiting_approval", planned
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    for child in planned["tree"]["plan"]["children"]:
        assert await job(api, root, child["dispatch_id"]) == "completed"
    assert await job(api, root) == "completed"
    return await read(api, root)


async def messages(api: SimpleNamespace, chat_id: UUID) -> list[dict[str, Any]]:
    response = await api.client.get(f"{CHATS}/{chat_id}/messages")
    assert response.status_code == 200, response.text
    return response.json()["items"]
