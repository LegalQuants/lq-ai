"""ADR 0038 D3: profiles and tools are the capability surface.

The contract: a profile and a tool that the product does not ship are added to
the registries, and are then offered, granted, recorded and presented with no
other change. Nothing in the engine, the routes, the views or the client's
fallback names them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any
from uuid import UUID

import pytest
from pydantic import Field, StringConstraints
from sqlalchemy import select
from tests.autonomous.orchestration.model_harness import (
    CHATS,
    approve,
    job,
    new_chat,
    read,
    start_in_chat,
    tool_call,
)

from app.api.dependencies import get_admin_user
from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import PhaseTools
from app.autonomous.orchestration.profiles import (
    RouteSettings,
    RunLimits,
    RunProfile,
    register_profile,
    registered_profiles,
    temporary_profile,
)
from app.autonomous.orchestration.tools import (
    RunTool,
    ToolCall,
    ToolInput,
    ToolOutcome,
    dumps,
    refusal,
    register_tool,
    registered_tools,
    temporary_tool,
)
from app.errors import ValidationError
from app.main import app
from app.models.audit import AuditLog
from app.models.orchestration import OrchestrationEffect as Effect, OrchestrationRoot

pytestmark = pytest.mark.integration

PROFILE = "contract_probe_v1"


class StampInput(ToolInput):
    label: Annotated[str, StringConstraints(min_length=1, max_length=40)] = Field(
        description="A short label to stamp."
    )


def _facts(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or "error" in data:
        return {"error": str((data or {}).get("error", "refused"))}
    return {"name": data["name"], "revision": data["revision"]}


async def _stamp(call: ToolCall) -> ToolOutcome:
    """A capability the product does not ship, reached through the chokepoint."""
    args = call.args
    assert isinstance(args, StampInput)
    result = await call.effects.workspace(
        call.claim,
        effect_key=call.effect_key,
        phase=call.phase,
        intent=ToolIntent.workspace_write,
        params={"name": "note-stamp.md", "revision": 0, "content": f"stamped: {args.label}"},
        step=call.note(_facts),
        tool_quote=call.quote,
    )
    if result.outcome == "workspace_refused":
        return ToolOutcome(refusal(str(result.data["error"]), "Not stamped."), ok=False)
    return ToolOutcome(dumps({"stamped": args.label}))


STAMP = RunTool(
    name="stamp_note",
    label="Stamp a probe note",
    description="Write a fixed probe note for this task.",
    intent=ToolIntent.workspace_write,
    input_model=StampInput,
    handler=_stamp,
    step_kind="probe_stamp",
    cost_usd=Decimal("0.0100"),
    pricing_version="probe-fixed-v1",
)


@pytest.fixture
def probe(model_demo: SimpleNamespace) -> Iterator[SimpleNamespace]:
    api = model_demo

    def route(settings: Any) -> RouteSettings:
        return RouteSettings(
            enabled=True,
            provider="selected",
            model="native",
            budget_usd=Decimal("3.0000"),
            minimum_tier=1,
            timeout_seconds=60,
            dedicated_project_id=str(api.env.project_id),
        )

    with (
        temporary_tool(STAMP),
        temporary_profile(
            RunProfile(
                id=PROFILE,
                title="Contract probe",
                summary="A profile the product does not ship.",
                reads="The installed fictional vendor agreement only.",
                root_skill="orchestration-chat-demo",
                child_skill="contract-qa",
                documents="packet",
                project_scope="dedicated",
                child_tools=PhaseTools(analysis=("read_document", "stamp_note")),
                limits=RunLimits(child_turn_limit=1),
                evidence="unverified",
                route=route,
                switch="registered by a test",
            )
        ),
    ):
        yield api


async def test_an_unshipped_profile_and_tool_are_offered_granted_recorded_and_presented(
    probe: SimpleNamespace,
) -> None:
    api = probe
    chat_id = await new_chat(api)

    # Offered: the composer lists the profile with its tools and allowances.
    listed = (await api.client.get(f"{CHATS}/{chat_id}/run-profiles")).json()
    offered = next(p for p in listed["profiles"] if p["profile"] == PROFILE)
    assert offered["available"] is True and offered["title"] == "Contract probe"
    assert [(t["name"], t["label"]) for t in offered["tools"]] == [
        ("read_document", "Read a selected document"),
        ("stamp_note", "Stamp a probe note"),
    ]
    unit = Decimal(offered["planning_allowance_usd"])
    # One tool turn and an answer, plus the priced tool's worst case for that turn.
    assert Decimal(offered["child_allowance_usd"]) == unit * 2 + Decimal("0.0100") * 8

    api.gateway.child_script = [
        [
            tool_call("stamp_note", {"label": "alpha", "reason": "Probe the registry."}, "call_a"),
            tool_call(
                "save_note", {"name": "note-x.md", "content": "x", "reason": "Ungranted."}, "b"
            ),
        ],
        None,
    ]
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    root = value["root_id"]
    assert value["profile"] == PROFILE and value["profile_title"] == "Contract probe"
    assert await job(api, root) == "completed"
    planned = await read(api, root)

    # Granted: the plan the owner approves lists each child's tools.
    plan = planned["tree"]["plan"]
    assert plan["profile"] == PROFILE and plan["contract_version"] == 3
    assert all(c["tools"]["analysis"] == ["read_document", "stamp_note"] for c in plan["children"])
    assert all(c["turn_limit"] == 1 for c in plan["children"])
    card = planned["tree"]["children"][0]["tools"]
    assert [(t["name"], t["label"], t["phase"]) for t in card] == [
        ("read_document", "Read a selected document", "analysis"),
        ("stamp_note", "Stamp a probe note", "analysis"),
    ]
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    child = plan["children"][0]["dispatch_id"]
    assert await job(api, root, child) == "completed"

    # The model was offered exactly the granted schemas, the unshipped one included.
    first = next(
        r
        for r in api.gateway.requests
        if r.tools and json.loads(r.messages[1].content)["inputs"]["operation"] != "propose_plan"
    )
    schemas = {t["function"]["name"]: t["function"] for t in first.tools}
    assert sorted(schemas) == ["read_document", "stamp_note"]
    assert schemas["stamp_note"]["parameters"]["required"] == ["reason", "label"]

    # Recorded: a priced, durable effect with the registry's step kind and reason.
    async with api.env.factory() as db:
        rows = {
            e.effect_key: e
            for e in await db.scalars(select(Effect).where(Effect.session_id == UUID(child)))
        }
        stamped, refused = rows["topic:t1:c0"], rows["topic:t1:c1"]
        assert stamped.intent == "workspace_write" and stamped.status == "completed"
        assert stamped.reserved_usd == stamped.charged_usd == Decimal("0.0100")
        assert stamped.result["step"] == {
            "kind": "probe_stamp",
            "tool": "stamp_note",
            "reason": "Probe the registry.",
            "summary": {"name": "note-stamp.md", "revision": 1},
        }
        # A shipped tool this profile does not grant is refused, by name.
        assert refused.intent == "refused" and refused.result["step"]["tool"] == "save_note"
        audit = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.resource_id == root, AuditLog.action == "orchestration.tool_refused"
                )
            )
        ).one()
        assert audit.details["tool"] == "save_note" and audit.details["code"] == "tool_not_granted"
        stored = await db.get(OrchestrationRoot, UUID(root))
        assert stored is not None and stored.profile == PROFILE

    # Presented: the owner's view carries the kind, the registry label and the summary.
    final = await read(api, root)
    steps = [e for e in final["tree"]["children"][0]["effects"] if e["step"]]
    probe_step = next(e for e in steps if e["step"]["kind"] == "probe_stamp")
    assert probe_step["step"]["label"] == "Stamp a probe note"
    assert probe_step["step"]["summary"] == {"name": "note-stamp.md", "revision": 1}
    assert Decimal(probe_step["charged_usd"]) == Decimal("0.0100")
    assert final["tree"]["mode"] == PROFILE and final["reads"].startswith("The installed")


async def test_the_operator_can_read_every_registry_profile_and_its_state(
    probe: SimpleNamespace,
) -> None:
    api = probe
    app.dependency_overrides[get_admin_user] = lambda: api.user
    try:
        response = await api.client.get("/api/v1/admin/orchestration/profiles")
    finally:
        app.dependency_overrides.pop(get_admin_user, None)
    assert response.status_code == 200, response.text
    value = response.json()
    states = {p["profile"]: p for p in value["profiles"]}
    assert set(states) == {"model_demo_v1", "new_harness_v1", PROFILE}
    assert value["deployment_children"] == 2
    fictional = states["model_demo_v1"]
    assert (
        fictional["enabled"] is True and fictional["switch"] == "LQ_AI_ORCHESTRATION_CHAT_ENABLED"
    )
    assert fictional["documents"] == "packet" and fictional["project_scope"] == "dedicated"
    assert fictional["limits"]["child_turn_limit"] == 2
    documents = states["new_harness_v1"]
    assert documents["enabled"] is False and documents["problem"] is None
    assert documents["switch"] == "LQ_AI_NEW_HARNESS_ENABLED"
    # The composer offers one profile as the New harness model; the operator sees which.
    assert documents["composer"] is True and fictional["composer"] is False
    assert states[PROFILE]["composer"] is False
    # It may start from a chat in any owned matter, or in none.
    assert documents["evidence"] == "citations" and documents["project_scope"] == "any"
    assert documents["documents"] == "optional"
    # Its two roles are instructed by engine prompt files, not installed skills.
    assert (documents["root_skill"], documents["child_skill"]) == ("", "")
    assert documents["root_prompt"] == "new_harness/orchestrator.v2"
    assert documents["child_prompt"] == "new_harness/subagent.v2"
    assert (fictional["root_prompt"], fictional["child_prompt"]) == ("", "")
    assert fictional["root_skill"] == "orchestration-chat-demo"
    # It follows the operator's gateway setting; the fixture still requires it.
    assert documents["pseudonymization"] == "operator"
    assert fictional["pseudonymization"] == "required"
    assert [t["name"] for t in states[PROFILE]["tools"]] == ["read_document", "stamp_note"]

    # A switch that is on with an incomplete configuration is reported, not enabled.
    api.runtime.settings.orchestration_chat_project_id = ""
    app.dependency_overrides[get_admin_user] = lambda: api.user
    try:
        broken = (await api.client.get("/api/v1/admin/orchestration/profiles")).json()
    finally:
        app.dependency_overrides.pop(get_admin_user, None)
    broken_state = next(p for p in broken["profiles"] if p["profile"] == "model_demo_v1")
    assert broken_state["enabled"] is False
    assert broken_state["problem"] == "Configure a dedicated demo project"


async def test_the_registry_read_is_for_administrators(model_demo: SimpleNamespace) -> None:
    response = await model_demo.client.get("/api/v1/admin/orchestration/profiles")
    assert response.status_code == 403


def test_the_registries_refuse_what_a_run_must_never_be_granted() -> None:
    shipped_tools = {t.name for t in registered_tools()}
    # The plan tool is not here: it is offered to the planning call only, and
    # no handler runs for it.
    assert shipped_tools == {"read_document", "read_note", "save_note", "search_knowledge_base"}
    assert {p.id for p in registered_profiles()} == {"model_demo_v1", "new_harness_v1"}

    def make(**changes: Any) -> RunTool:
        base: dict[str, Any] = {
            "name": "probe_tool",
            "label": "Probe",
            "description": "Probe.",
            "intent": ToolIntent.workspace_read,
            "input_model": StampInput,
            "handler": _stamp,
            "step_kind": "probe",
        }
        return RunTool(**{**base, **changes})

    # Destructive and confirmation-required tools cannot be registered for runs.
    for bad in (
        make(destructive=True),
        make(requires_confirmation=True),
        make(name="Not Valid"),
        make(label=" "),
        make(cost_usd=Decimal("-1")),
        make(name="read_document"),
    ):
        with pytest.raises(ValidationError):
            register_tool(bad)
    assert {t.name for t in registered_tools()} == shipped_tools

    shipped = next(p for p in registered_profiles() if p.id == "model_demo_v1")
    for changes in (
        {"id": "model_demo_v1"},
        {"id": "demonstration"},
        {"id": "Bad-Id"},
        {"id": "probe_a", "child_tools": PhaseTools(analysis=("not_registered",))},
        # A tool grant without a turn limit, and a turn limit without tools.
        {"id": "probe_b", "limits": RunLimits(child_turn_limit=0)},
        {"id": "probe_c", "child_tools": PhaseTools()},
        # A second profile offered in the composer: nothing says which a request would run.
        {"id": "probe_d", "composer": True},
    ):
        with pytest.raises(ValidationError):
            register_profile(RunProfile(**{**shipped.__dict__, **changes}))
    with pytest.raises(ValidationError):
        RunLimits(max_input_bytes=2_000_000)
    assert {p.id for p in registered_profiles()} == {"model_demo_v1", "new_harness_v1"}
