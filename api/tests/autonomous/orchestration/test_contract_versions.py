"""Consent bindings survive the contract changes of ADR 0038.

A plan's hash is what the owner approved, and an effect's identity is what was
admitted. Fields added for registry profiles, tool grants and tool turns must
not enter the canonical form of anything retained from 0.8.0.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.autonomous.orchestration.contracts import DocumentRef, PhaseTools, PreparedPlan
from app.autonomous.orchestration.inference import (
    InferenceBinding,
    TokenRates,
    bound_result,
    conversation_identity,
    message_identity,
)
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import InferencePolicy
from app.errors import ValidationError

pytestmark = pytest.mark.unit

RECORDED = Path(__file__).resolve().parents[4] / "docs" / "uat" / "adr35-chat"
RUNS = (
    "model-run.json",
    "rejected-run.json",
    "stalled-model-run.json",
    "timeout-run.json",
    "fenced-plan-run.json",
    "truncated-plan-run.json",
)


@pytest.mark.parametrize("name", RUNS)
def test_a_recorded_0_8_0_run_keeps_its_plan_hash_and_planning_digest(name: str) -> None:
    run = json.loads((RECORDED / name).read_text())
    snapshot = PlanningSnapshot.model_validate_json(json.dumps(run["planning"]))
    assert snapshot.contract_version == 1 and snapshot.profile is None
    # The retained intake serializes to exactly what was stored.
    assert snapshot.model_dump(mode="json") == run["planning"]
    if run["tree"] is None:
        return
    plan = PreparedPlan.model_validate_json(json.dumps(run["tree"]["plan"]))
    assert plan.contract_version == 2
    assert plan.approval_hash() == run["tree"]["plan_hash"]
    assert plan.planning_digest == snapshot.approval_hash()
    dumped = plan.model_dump(mode="json")
    assert dumped == run["tree"]["plan"]
    assert "profile" not in dumped and "documents" not in dumped
    assert all("tools" not in c and "turn_limit" not in c for c in dumped["children"])


def _recorded_plan() -> dict[str, Any]:
    return json.loads((RECORDED / "model-run.json").read_text())["tree"]["plan"]


def test_version_three_binds_the_profile_tools_and_numbered_documents() -> None:
    plan = _recorded_plan()
    document_id, file_id = uuid4(), uuid4()
    for scope in (plan["root"], *(c["execution"] for c in plan["children"])):
        scope["resources"]["document_ids"] = [str(document_id)]
        scope["grants"]["analysis"] = sorted({*scope["grants"]["analysis"], "retrieve_chunks"})
    plan["delegation_grants"]["analysis"] = sorted(
        {*plan["delegation_grants"]["analysis"], "retrieve_chunks"}
    )
    plan.update(
        contract_version=3,
        profile="model_demo_v1",
        documents=[
            {
                "number": 1,
                "document_id": str(document_id),
                "file_id": str(file_id),
                "filename": "agreement.md",
                "attached_for_run": False,
            }
        ],
    )
    for child in plan["children"]:
        child["tools"] = {"analysis": ["read_document"]}
        child["turn_limit"] = 2
    approved = PreparedPlan.model_validate_json(json.dumps(plan))
    baseline = approved.approval_hash()

    def changed(mutate: Any) -> str:
        value = json.loads(json.dumps(plan))
        mutate(value)
        return PreparedPlan.model_validate_json(json.dumps(value)).approval_hash()

    # Each of these is part of what the owner consents to.
    assert changed(lambda v: v.update(profile="another_profile")) != baseline
    assert changed(lambda v: v["documents"][0].update(filename="other.md")) != baseline
    assert changed(lambda v: v["documents"][0].update(attached_for_run=True)) != baseline
    assert changed(lambda v: v["children"][0].update(turn_limit=3)) != baseline
    assert (
        changed(lambda v: v["children"][0]["tools"].update(analysis=["read_document", "save_note"]))
        != baseline
    )

    def refused(mutate: Any) -> None:
        value = json.loads(json.dumps(plan))
        mutate(value)
        with pytest.raises(ValueError):
            PreparedPlan.model_validate_json(json.dumps(value))

    # A numbered list that differs from the root's resource scope.
    refused(lambda v: v["documents"].clear())
    refused(lambda v: v["documents"][0].update(number=2))
    refused(lambda v: v["documents"][0].update(document_id=str(uuid4())))
    # A registry plan names its profile; tools and a turn limit come together.
    refused(lambda v: v.update(profile=None))
    refused(lambda v: v["children"][0].update(turn_limit=0))
    refused(lambda v: v["children"][0].update(tools={}))
    refused(lambda v: v["children"][0]["tools"].update(analysis=["read_document"] * 2))
    # An earlier contract version cannot carry the new authority.
    refused(lambda v: v.update(contract_version=2))


def test_a_snapshot_is_versioned_like_a_plan() -> None:
    recorded = json.loads((RECORDED / "model-run.json").read_text())["planning"]
    legacy = PlanningSnapshot.model_validate_json(json.dumps(recorded))
    document = DocumentRef(number=1, document_id=uuid4(), file_id=uuid4(), filename="agreement.md")
    scope = legacy.root.model_copy(
        update={
            "resources": legacy.root.resources.model_copy(
                update={"document_ids": (document.document_id,)}
            )
        }
    )
    registry = PlanningSnapshot.model_validate(
        {
            **legacy.model_dump(),
            "contract_version": 2,
            "profile": "contract_qa_documents_v1",
            "documents": (document,),
            "root": scope,
            "packet_digest": None,
            "max_children": 2,
        }
    )
    dumped = registry.model_dump(mode="json")
    assert dumped["profile"] == "contract_qa_documents_v1" and dumped["max_children"] == 2
    assert dumped["documents"][0]["filename"] == "agreement.md"
    assert registry.approval_hash() != legacy.approval_hash()
    # Version 1 is the fixed fictional packet and cannot carry a selection.
    for change in (
        {"profile": "model_demo_v1"},
        {"packet_digest": None},
        {"max_children": 2},
    ):
        with pytest.raises(ValueError):
            PlanningSnapshot.model_validate({**legacy.model_dump(), **change})
    with pytest.raises(ValueError):
        PlanningSnapshot.model_validate({**registry.model_dump(), "profile": None})
    with pytest.raises(ValueError):
        PlanningSnapshot.model_validate({**registry.model_dump(), "documents": ()})


def test_two_pinned_messages_keep_the_identity_0_8_0_computed() -> None:
    messages = [{"role": "system", "content": "pinned ✓"}, {"role": "user", "content": "task"}]
    legacy = hashlib.sha256(
        json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert message_identity(messages) == (legacy, len("pinned ✓".encode()) + 4)
    assert conversation_identity(messages) == message_identity(messages)
    # Offering a schema, or adding a turn, is a different request.
    tools = [{"type": "function", "function": {"name": "read_document"}}]
    assert conversation_identity(messages, tools)[0] != legacy
    assert conversation_identity(messages, tools)[1] > len("pinned ✓".encode()) + 4


def test_the_conversation_shape_is_closed() -> None:
    system = {"role": "system", "content": "pinned"}
    user = {"role": "user", "content": "task"}
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "read_document", "arguments": "{}"},
    }
    assistant = {"role": "assistant", "content": "", "tool_calls": [call]}
    tool = {"role": "tool", "tool_call_id": "c1", "content": "result"}
    final = {"role": "user", "content": "Tool use has ended."}
    digest, size = conversation_identity([system, user, assistant, tool, final])
    assert len(digest) == 64 and size > len("pinnedtaskresult")

    for bad in (
        [user, system],  # the pinned system prompt comes first
        [system, assistant],  # the task comes second
        [system, user, {"role": "system", "content": "a second system prompt"}],
        [system, user, {**assistant, "name": "extra"}],
        [system, user, {**tool, "extra": True}],
        [system, user, {"role": "tool", "content": "no call id"}],
        [system, user, {**assistant, "tool_calls": [{**call, "function": {"name": "x"}}]}],
        [system, user, {**assistant, "tool_calls": [call] * 9}],
        [system, user, {"role": "assistant", "content": None}],
        [system],
        "not a list",
    ):
        with pytest.raises(ValidationError):
            conversation_identity(bad)
    with pytest.raises(ValidationError):
        conversation_identity([system, user], tools=["not a schema"])
    with pytest.raises(ValidationError, match="bounded request size"):
        conversation_identity([system, {"role": "user", "content": "x" * 200}], max_bytes=128)
    # The two-message entry point stays two messages.
    with pytest.raises(ValidationError):
        message_identity([system, user, final])


def _binding(*, tools: bool) -> InferenceBinding:
    return InferenceBinding(
        policy_version="p",
        policy=InferencePolicy(
            provider="selected", native_model="native", max_input_bytes=98304, max_output_tokens=64
        ),
        routed_tier=1,
        rates=TokenRates(input_per_mtok=Decimal("2"), output_per_mtok=Decimal("6")),
        messages_digest="a" * 64,
        estimated_prompt_tokens=100,
        reservation_usd=Decimal("0.0010"),
        config_digest="b" * 64,
        gateway_revision="c" * 64,
        anonymization_expected=True,
        tools_offered=tools,
    )


def _response(*, content: Any, tool_calls: Any = None, finish: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        routed_provider="selected",
        routed_model="native",
        routed_inference_tier=1,
        anonymization_applied=True,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=finish,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


def test_a_binding_without_tools_keeps_its_0_8_0_form() -> None:
    assert "tools_offered" not in _binding(tools=False).model_dump(mode="json")
    assert _binding(tools=True).model_dump(mode="json")["tools_offered"] is True


def test_tool_calls_are_normalized_into_bounded_data() -> None:
    calls = [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "read_document", "arguments": '{"a":1}'},
        },
        # A provider that returns arguments as an object.
        {"id": "", "function": {"name": "save_note", "arguments": {"b": 2}}},
        # Malformed entries are kept empty so the loop refuses them.
        {"id": 7, "function": {"name": None, "arguments": 5}},
        "not a call",
        *({"id": f"x{i}", "function": {"name": "n", "arguments": "{}"}} for i in range(20)),
    ]
    result = bound_result(
        _binding(tools=True),
        _response(content=None, tool_calls=calls, finish="stop"),
        intent="run_skill",
    )
    data = result.data
    assert data["finish_reason"] == "tool_calls" and data["content"] == ""
    assert len(data["tool_calls"]) == 8  # the cap
    assert data["tool_calls"][0] == {"id": "c1", "name": "read_document", "arguments": '{"a":1}'}
    assert data["tool_calls"][1] == {"id": "call_1", "name": "save_note", "arguments": '{"b": 2}'}
    assert data["tool_calls"][2] == {"id": "call_2", "name": "", "arguments": ""}
    assert data["tool_calls"][3] == {"id": "call_3", "name": "", "arguments": ""}
    assert data["accounting"]["tier"] == 1 and data["accounting"]["anonymization_applied"] is True
    assert result.cost_usd >= Decimal("0.0010")


def test_calls_that_were_not_offered_are_dropped_and_the_reply_is_not_an_answer() -> None:
    call = {"id": "c1", "function": {"name": "read_document", "arguments": "{}"}}
    result = bound_result(
        _binding(tools=False),
        _response(content="Let me read it.", tool_calls=[call], finish="tool_calls"),
        intent="run_skill",
    )
    # The provider outcome is known, so this is not an uncertain effect.
    assert "tool_calls" not in result.data
    # Callers accept only ``stop``; a partial preamble is never taken as the answer.
    assert result.data["finish_reason"] == "tool_calls"
    # An ordinary reply is unchanged.
    plain = bound_result(_binding(tools=False), _response(content="Answer."), intent="run_skill")
    assert plain.data["finish_reason"] == "stop" and plain.data["content"] == "Answer."
    for bad in (
        _response(content=None),
        _response(content="x", finish="function_call"),
        _response(content="x", tool_calls="not a list"),
    ):
        with pytest.raises(ValidationError, match="reconciliation is required"):
            bound_result(_binding(tools=True), bad, intent="run_skill")


def test_tool_names_are_unique_and_ordered_in_a_grant() -> None:
    grant = PhaseTools(analysis=("save_note", "read_document"))
    assert grant.analysis == ("read_document", "save_note")
    assert grant.names() == {"read_document", "save_note"}
    assert grant.contains(PhaseTools(analysis=("read_document",)))
    assert not grant.contains(PhaseTools(drafting=("read_document",)))
    with pytest.raises(ValueError):
        PhaseTools(analysis=("read_document", "read_document"))
