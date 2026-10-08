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
from uuid import UUID, uuid4

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
            "profile": "new_harness_v1",
            "documents": (document,),
            "root": scope,
            "packet_digest": None,
            "max_children": 2,
        }
    )
    dumped = registry.model_dump(mode="json")
    assert dumped["profile"] == "new_harness_v1" and dumped["max_children"] == 2
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


# --- Golden hashes: what was approved must hash as it did ---------------------------------
#
# A plan's hash is what the owner consented to, and a retained plan is checked against it
# every time it is loaded. The fields added for knowledge bases and for a run's terms must
# leave no trace in the canonical form of anything that has none, or every retained plan
# stops matching its own hash. These literals are the digests as recorded; a change to a
# serializer shows here as a changed literal.

NEW_KEYS = frozenset({"knowledge_base_ids", "knowledge_bases", "terms"})

# (intake digest, plan digest or None), as recorded in docs/uat/adr35-chat in 0.8.0.
RECORDED_DIGESTS = {
    "model-run.json": (
        "efeac949c6698ece11a5fc990f7b2660181896d4767d6011a9ccc4f585326b84",
        "05c9d5c97c553f14b6f42d7528daa94960508afd8a55b9af295b1d8fd839306d",
    ),
    "rejected-run.json": (
        "b0cf7b2c98665d30ada0e4852e8511350df99162492072c455c6c97f7f24f60b",
        "8340e3b5b26e3333bc40fe2ded40847b879f3c1f611f13504bfabf2005a1693c",
    ),
    "stalled-model-run.json": (
        "cfcbbaeba0873af325f2dfb795b59a83a136f3e78c082dcd467f6ed5713015b0",
        "f155544164c4e5a3507428106cb17a8afd5b48e3fba7a80107893cb3169d7006",
    ),
    "timeout-run.json": (
        "d6da0d1cb5326721d12b1a827d255432150e250f02ca4ffbed510f61df971547",
        "e5a0976c0a85c459d637b00465b61521f76588d91cee55c34234be27475f9fa4",
    ),
    "fenced-plan-run.json": (
        "8277b259142264620f4470ad60b417df328c771c87f15cbdf5775a4d569deaca",
        None,
    ),
    "truncated-plan-run.json": (
        "001aa8e5c5fe398334133df16d264360550ecb9832df8d5a3925c0dbc611b7bc",
        None,
    ),
}
# Registry contracts built below from fixed identifiers, with no knowledge base and no
# terms, as increments 1 and 2 built them. Digests computed when the fields were added.
FIXED_DIGESTS = {
    "v2_snapshot": "8bb171ffe6c3ac7e5beb7d36ed2ce83a1674895bc1104291a0e1bf2a295a336b",
    "v3_snapshot": "16921adce4e88e97e30fa348fc90201c18ed13b2f3377e3c99debce2734f098b",
    "v3_plan": "61e16e856ae51d4cbe14b6e2e80900566b8356c4699a1be4951a920ae067a760",
}
DOCUMENT = {
    "number": 1,
    "document_id": str(UUID(int=0xD0C)),
    "file_id": str(UUID(int=0xF11E)),
    "filename": "agreement.md",
    "attached_for_run": False,
}
KNOWLEDGE_BASE = {"knowledge_base_id": str(UUID(int=0xB5)), "name": "Policies"}


def _keys_in(value: Any) -> set[str]:
    """Every key of every object nested anywhere in a dump."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys_in(v)}
    return set()


def _canonical_hash(dump: dict[str, Any]) -> str:
    """The canonical form a hash is taken over: sorted keys, compact separators."""
    return hashlib.sha256(
        json.dumps(dump, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _recorded(name: str) -> dict[str, Any]:
    return json.loads((RECORDED / name).read_text())


@pytest.mark.parametrize("name", RUNS)
def test_a_recorded_0_8_0_run_has_the_digests_it_had_and_none_of_the_new_keys(name: str) -> None:
    run = _recorded(name)
    intake_digest, plan_digest = RECORDED_DIGESTS[name]
    snapshot = PlanningSnapshot.model_validate_json(json.dumps(run["planning"]))
    dumped = snapshot.model_dump(mode="json")
    assert not NEW_KEYS & _keys_in(dumped)
    assert snapshot.approval_hash() == intake_digest == _canonical_hash(dumped)
    assert (run["tree"] is None) is (plan_digest is None)
    if plan_digest is None:
        return
    plan = PreparedPlan.model_validate_json(json.dumps(run["tree"]["plan"]))
    dumped_plan = plan.model_dump(mode="json")
    assert not NEW_KEYS & _keys_in(dumped_plan)
    assert plan.approval_hash() == plan_digest == run["tree"]["plan_hash"]
    assert plan.approval_hash() == _canonical_hash(dumped_plan)


def _version_two_snapshot() -> dict[str, Any]:
    """A registry intake as increment 1 recorded it: a profile and a numbered selection."""
    snapshot = _recorded("model-run.json")["planning"]
    snapshot["root"]["resources"]["document_ids"] = [DOCUMENT["document_id"]]
    snapshot.update(
        contract_version=2,
        profile="new_harness_v1",
        documents=[DOCUMENT],
        packet_digest=None,
        max_children=2,
    )
    return snapshot


def _version_three_snapshot() -> dict[str, Any]:
    """A registry intake as increment 2 recorded it: the chat so far and the date."""
    snapshot = _version_two_snapshot()
    snapshot.update(
        contract_version=3,
        today="2026-01-02",
        thread=[
            {"role": "user", "content": "An earlier question.", "cut": False},
            {"role": "assistant", "content": "An earlier answer.", "cut": True},
        ],
    )
    return snapshot


def _version_three_plan() -> dict[str, Any]:
    """A registry plan as increment 2 approved it, built as the version 3 test above builds one."""
    plan = _recorded("model-run.json")["tree"]["plan"]
    for scope in (plan["root"], *(c["execution"] for c in plan["children"])):
        scope["resources"]["document_ids"] = [DOCUMENT["document_id"]]
        scope["grants"]["analysis"] = sorted({*scope["grants"]["analysis"], "retrieve_chunks"})
    plan["delegation_grants"]["analysis"] = sorted(
        {*plan["delegation_grants"]["analysis"], "retrieve_chunks"}
    )
    plan.update(contract_version=3, profile="new_harness_v1", documents=[DOCUMENT])
    for child in plan["children"]:
        child["tools"] = {"analysis": ["read_document"]}
        child["turn_limit"] = 2
    return plan


def _with_a_knowledge_base(contract: dict[str, Any]) -> dict[str, Any]:
    """The same contract with one knowledge base listed, as a run in a matter lists it."""
    value = json.loads(json.dumps(contract))
    scopes = [value["root"], *(c["execution"] for c in value.get("children", ()))]
    for scope in scopes:
        scope["resources"]["knowledge_base_ids"] = [KNOWLEDGE_BASE["knowledge_base_id"]]
    value["knowledge_bases"] = [KNOWLEDGE_BASE]
    return value


TERMS = {
    "task_turns": 5,
    "task_answer_chars": 12000,
    "answer_chars": 16384,
    "read_chars": 40000,
    "planning": "tool",
}


def test_a_registry_contract_without_knowledge_bases_or_terms_keeps_its_digest() -> None:
    contracts: dict[str, PlanningSnapshot | PreparedPlan] = {
        "v2_snapshot": PlanningSnapshot.model_validate_json(json.dumps(_version_two_snapshot())),
        "v3_snapshot": PlanningSnapshot.model_validate_json(json.dumps(_version_three_snapshot())),
        "v3_plan": PreparedPlan.model_validate_json(json.dumps(_version_three_plan())),
    }
    assert [c.contract_version for c in contracts.values()] == [2, 3, 3]
    for name, contract in contracts.items():
        dumped = contract.model_dump(mode="json")
        # Nothing of the newer fields is in the canonical form, and the hash is the literal.
        assert not NEW_KEYS & _keys_in(dumped), name
        assert contract.approval_hash() == _canonical_hash(dumped), name
        assert contract.approval_hash() == FIXED_DIGESTS[name], name


def test_listing_a_knowledge_base_or_stating_terms_changes_the_digest_and_the_dump() -> None:
    snapshot, plan = _version_three_snapshot(), _version_three_plan()
    for kind, contract, model in (
        ("snapshot", snapshot, PlanningSnapshot),
        ("plan", plan, PreparedPlan),
    ):
        plain = model.model_validate_json(json.dumps(contract))
        listed = model.model_validate_json(json.dumps(_with_a_knowledge_base(contract)))
        assert listed.approval_hash() != plain.approval_hash(), kind
        dumped = listed.model_dump(mode="json")
        assert {"knowledge_base_ids", "knowledge_bases"} <= _keys_in(dumped), kind
        assert listed.approval_hash() == _canonical_hash(dumped), kind
        # Taking it out again gives back the digest it had.
        again = json.loads(json.dumps(dumped))
        again.pop("knowledge_bases")
        for scope in (again["root"], *(c["execution"] for c in again.get("children", ()))):
            scope["resources"].pop("knowledge_base_ids")
        assert model.model_validate_json(json.dumps(again)).approval_hash() == plain.approval_hash()
    # Terms are part of an intake that has them, and of nothing else.
    plain_snapshot = PlanningSnapshot.model_validate_json(json.dumps(snapshot))
    with_terms = PlanningSnapshot.model_validate_json(json.dumps({**snapshot, "terms": TERMS}))
    assert "terms" in with_terms.model_dump(mode="json")
    assert with_terms.approval_hash() != plain_snapshot.approval_hash()
    assert with_terms.approval_hash() == _canonical_hash(with_terms.model_dump(mode="json"))
    # Each of the terms changes it, and the way the plan is handed over does.
    for change in ({"task_turns": 4}, {"read_chars": 20000}, {"planning": "text"}):
        other = PlanningSnapshot.model_validate_json(
            json.dumps({**snapshot, "terms": {**TERMS, **change}})
        )
        assert other.approval_hash() != with_terms.approval_hash()
    # An earlier contract version cannot carry either.
    for refused in (
        {**_version_two_snapshot(), "terms": TERMS},
        _with_a_knowledge_base(_version_two_snapshot()),
    ):
        with pytest.raises(ValueError):
            PlanningSnapshot.model_validate_json(json.dumps(refused))
