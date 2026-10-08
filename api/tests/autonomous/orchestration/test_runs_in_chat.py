"""ADR 0038 D1 and D2: a governed run as a turn in the chat, as visible as any turn.

Real Postgres, store, guard, worker and checkpoint paths; the provider is
controlled. These tests establish the contract. A configured-provider
acceptance run is a separate gate.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from tests.autonomous.orchestration.model_harness import (
    BASE,
    CHATS,
    GOAL,
    approve,
    job,
    messages,
    new_chat,
    read,
    run_to_completion,
    start,
    start_in_chat,
)

from app.api.chats import _load_history_messages
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.inference import InferenceRoutingLog
from app.models.orchestration import OrchestrationRoot
from app.models.user import User
from app.models.work_product import WorkProductAttribution

pytestmark = pytest.mark.integration


async def profiles(api: SimpleNamespace, chat_id: object) -> dict:
    response = await api.client.get(f"{CHATS}/{chat_id}/run-profiles")
    assert response.status_code == 200, response.text
    return response.json()


def by_id(value: dict, profile: str) -> dict:
    return next(p for p in value["profiles"] if p["profile"] == profile)


async def test_a_run_is_one_turn_in_the_thread_and_delivers_into_its_message(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)

    offered = await profiles(api, chat_id)
    fictional = by_id(offered, "model_demo_v1")
    assert fictional["available"] is True and fictional["reason"] is None
    assert fictional["model"] == "selected/native"
    assert Decimal(fictional["budget_usd"]) == Decimal("2.0000")
    assert Decimal(fictional["planning_allowance_usd"]) > 0
    # A task is allowed one unit per model call it may make: two tool turns and an answer.
    assert Decimal(fictional["child_allowance_usd"]) == 3 * Decimal(
        fictional["planning_allowance_usd"]
    )
    assert fictional["max_children"] == 2 and fictional["child_turn_limit"] == 2
    assert [t["name"] for t in fictional["tools"]] == ["read_document", "read_note", "save_note"]
    assert "request only" in fictional["planning_notice"]
    # The button is Send, and the notice says what sending does.
    assert fictional["planning_notice"].startswith("Sending asks the model for a plan")
    assert "until you approve the plan" in fictional["planning_notice"]
    # The composer is told which profile it offers. The fictional one is not it.
    assert offered["composer_profile"] == "new_harness_v1"
    assert offered["active_run"] is None
    # Enabling the fictional profile never enables the real-document one.
    documents = by_id(offered, "new_harness_v1")
    assert documents["available"] is False and documents["reason"] == "operator_disabled"
    assert not api.gateway.requests

    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    assert value["status"] == "planning" and value["chat_id"] == str(chat_id)
    thread = await messages(api, chat_id)
    assert [(m["role"], m["kind"]) for m in thread] == [("user", "user"), ("assistant", "run")]
    assert thread[0]["content"] == GOAL
    run_message = thread[1]
    assert run_message["id"] == value["message_id"]
    assert run_message["autonomous_session_id"] == root
    assert run_message["content"] == "" and run_message["applied_skills"] == []
    async with api.env.factory() as db:
        chat = await db.get(Chat, chat_id)
        assert chat is not None and chat.title == GOAL[:80].strip()

    # While active, every composer names the run that holds the allowance.
    elsewhere = await profiles(api, await new_chat(api, title="Another chat"))
    assert by_id(elsewhere, "model_demo_v1")["reason"] == "active_run"
    assert elsewhere["active_run"]["root_id"] == root
    assert elsewhere["active_run"]["chat_id"] == str(chat_id)
    assert elsewhere["active_run"]["chat_title"] == GOAL[:80].strip()

    final = await run_to_completion(api, value)
    assert final["status"] == "completed" and final["tree"]["result"]["coverage"] == "complete"

    delivered = (await messages(api, chat_id))[1]
    assert delivered["id"] == run_message["id"]
    assert delivered["content"] == api.gateway.synthesis_answer
    # The fields an ordinary assistant turn carries (D2).
    assert delivered["applied_skills"] == ["orchestration-chat-demo", "contract-qa"]
    assert delivered["routed_provider"] == "selected" and delivered["routed_model"] == "native"
    assert delivered["routed_inference_tier"] == 1
    assert delivered["requested_model"] == "selected/native"
    calls = len(api.gateway.requests)
    assert calls == 1 + 2 * 2 + 1  # plan, two children of two turns, synthesis
    assert delivered["prompt_tokens"] == 20 * calls
    assert delivered["completion_tokens"] == 30 * calls
    assert Decimal(str(delivered["cost_estimate"])) == Decimal(final["spent_usd"])

    # Every model call of the run carried the chat and message identifiers.
    assert set(api.gateway.correlations) == {(str(chat_id), run_message["id"], "orchestration_run")}

    async with api.env.factory() as db:
        delivery = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.resource_id == root, AuditLog.action == "orchestration.root_delivered"
                )
            )
        ).one()
        assert delivery.details["message_id"] == run_message["id"]
        assert delivery.details["chat_id"] == str(chat_id)
        assert delivery.details["verification"] == "unverified"
        # The answer is not copied into the audit row.
        assert api.gateway.synthesis_answer not in json.dumps(delivery.details)
        # The chain-of-custody row an ordinary answered turn gets (PRD §3.3).
        attribution = (
            await db.scalars(
                select(WorkProductAttribution).where(
                    WorkProductAttribution.message_id == UUID(run_message["id"])
                )
            )
        ).one()
        assert attribution.user_id == api.env.owner_id and attribution.chat_id == chat_id
        assert attribution.project_id == api.env.project_id
        assert (attribution.provider, attribution.model) == ("selected", "native")
        assert attribution.routed_inference_tier == 1
        assert attribution.skill_ids == ["orchestration-chat-demo", "contract-qa"]
        assert (
            attribution.content_hash
            == hashlib.sha256(api.gateway.synthesis_answer.encode()).hexdigest()
        )

    # The allowance is free again.
    assert by_id(await profiles(api, chat_id), "model_demo_v1")["available"] is True


async def test_text_reaches_the_model_as_itself_and_not_as_escapes(
    model_demo: SimpleNamespace,
) -> None:
    """A section mark, a curly quote and a non-Latin word are sent as characters.

    Run inputs travel as JSON. When they were escaped as ``\\uXXXX``, a local
    model told to keep quotations exactly copied the escape into its answer,
    which then showed ``[\\u00a72]`` and could not match the document.
    """
    api = model_demo
    chat_id = await new_chat(api)
    goal = "Was regelt \u00a7 5 zur Verl\u00e4ngerung? Explain \u201crenewal\u201d \u2014 and \u652f\u4ed8."
    value = await start_in_chat(api, chat_id, goal=goal)
    await run_to_completion(api, value)
    sent = [request.messages[1].content for request in api.gateway.requests]
    assert len(sent) >= 4
    # The planning call carries the request; the last call combines the tasks'
    # findings, which cite "[\u00a75]".
    assert "\u00a7 5 zur Verl\u00e4ngerung" in sent[0] and "\u652f\u4ed8" in sent[0]
    assert "[\u00a75]" in sent[-1]
    for content in sent:
        assert "\\u00a7" not in content and "\\u201c" not in content and "\\u652f" not in content
        json.loads(content)


async def test_later_turns_see_a_delivered_answer_and_never_an_empty_run(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    rejected = await start_in_chat(api, chat_id, goal="First request, to be rejected.")
    assert await job(api, rejected["root_id"]) == "completed"
    response = await api.client.post(f"{BASE}/{rejected['root_id']}/reject", json={"revision": 1})
    assert response.status_code == 200 and response.json()["status"] == "rejected"

    delivered = await start_in_chat(api, chat_id, goal="Second request, delivered.")
    await run_to_completion(api, delivered)

    thread = await messages(api, chat_id)
    assert [m["kind"] for m in thread] == ["user", "run", "user", "run"]
    assert thread[1]["content"] == "" and thread[3]["content"] == api.gateway.synthesis_answer

    async with api.env.factory() as db:
        history = await _load_history_messages(
            db, chat_id=chat_id, exclude_message_id=uuid4(), token_budget=100_000, max_messages=50
        )
    assert [(m.role, m.content) for m in history] == [
        ("user", "First request, to be rejected."),
        ("user", "Second request, delivered."),
        ("assistant", api.gateway.synthesis_answer),
    ]


async def test_a_repeated_send_returns_the_same_run_and_writes_no_second_turn(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    request_id = str(uuid4())
    first = await start_in_chat(api, chat_id, request_id=request_id)
    again = await start_in_chat(api, chat_id, request_id=request_id)
    assert again["root_id"] == first["root_id"] == request_id
    assert again["message_id"] == first["message_id"]
    assert len(await messages(api, chat_id)) == 2
    # The repeated send did not queue planning a second time.
    assert api.queued.count((UUID(request_id), UUID(request_id))) == 1

    # The same identity cannot be reused for different input or another chat.
    await start_in_chat(api, chat_id, request_id=request_id, goal="A different goal.", expect=409)
    other = await new_chat(api, title="Other")
    await start_in_chat(api, other, request_id=request_id, expect=409)
    assert await messages(api, other) == []
    assert not api.gateway.requests


async def test_each_refusal_writes_no_messages_and_makes_no_model_call(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)

    # A chat outside a matter.
    loose = await new_chat(api, in_project=False)
    await start_in_chat(api, loose, expect=403)
    assert by_id(await profiles(api, loose), "model_demo_v1")["reason"] == "project_required"

    # An archived chat, and a chat that is not there.
    archived = await new_chat(api)
    async with api.env.factory.begin() as db:
        await db.execute(
            update(Chat).where(Chat.id == archived).values(archived_at=Chat.created_at)
        )
    await start_in_chat(api, archived, expect=404)
    await start_in_chat(api, uuid4(), expect=404)

    # A profile that is not in the registry, and one the operator has not enabled.
    await start_in_chat(api, chat_id, profile="made_up_profile", expect=403)
    await start_in_chat(api, chat_id, profile="new_harness_v1", expect=403)

    # The fictional profile reads a fixed document; a selection is refused.
    await start_in_chat(api, chat_id, file_ids=[str(uuid4())], expect=400)

    # The owner's Autonomous opt-in.
    api.user.autonomous_enabled = False
    await start_in_chat(api, chat_id, expect=403)
    assert by_id(await profiles(api, chat_id), "model_demo_v1")["reason"] == (
        "autonomous_opt_in_required"
    )
    api.user.autonomous_enabled = True

    # The operator switch.
    api.runtime.settings.orchestration_chat_enabled = False
    await start_in_chat(api, chat_id, expect=403)
    assert by_id(await profiles(api, chat_id), "model_demo_v1")["reason"] == "operator_disabled"
    api.runtime.settings.orchestration_chat_enabled = True

    # An unpriced route.
    rates = api.gateway.config["cost_tracking"]["rates"]
    api.gateway.config["cost_tracking"]["rates"] = {}
    await start_in_chat(api, chat_id, expect=403)
    unpriced = by_id(await profiles(api, chat_id), "model_demo_v1")
    assert unpriced["reason"] == "route_unavailable" and unpriced["model"] is None
    api.gateway.config["cost_tracking"]["rates"] = rates

    for chat in (chat_id, loose, archived):
        assert await messages(api, chat) == []
    assert not api.gateway.requests and not api.queued
    async with api.env.factory() as db:
        mine = select(OrchestrationRoot.session_id).where(
            OrchestrationRoot.owner_id == api.env.owner_id
        )
        assert not (await db.scalars(mine)).all()

    # One active run per owner: a second start is refused and names nothing new.
    first = await start_in_chat(api, chat_id)
    second_chat = await new_chat(api)
    await start_in_chat(api, second_chat, expect=409)
    assert await messages(api, second_chat) == []
    assert (await profiles(api, second_chat))["active_run"]["root_id"] == first["root_id"]


async def test_another_owner_cannot_start_read_or_list_through_this_chat(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    async with api.env.factory.begin() as db:
        stranger = User(
            email=f"stranger-{uuid4()}@example.com",
            hashed_password="unused-test",
            autonomous_enabled=True,
        )
        db.add(stranger)
        await db.flush()
        stranger_id = stranger.id
    owner_id = api.user.id
    api.user.id = stranger_id
    try:
        assert (await api.client.get(f"{CHATS}/{chat_id}/run-profiles")).status_code == 404
        assert (await api.client.get(f"{CHATS}/{chat_id}/run-documents")).status_code == 404
        await start_in_chat(api, chat_id, expect=404)
        assert (await api.client.get(f"{BASE}/chat-runs/{value['root_id']}")).status_code == 404
    finally:
        api.user.id = owner_id
        async with api.env.factory.begin() as db:
            await db.execute(delete(User).where(User.id == stranger_id))


async def test_halt_and_a_failed_plan_leave_the_message_empty_and_readable(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    halted = await api.client.post(f"{BASE}/chat-runs/{root}/halt")
    assert halted.status_code == 200 and halted.json()["status"] == "halted"
    assert (await messages(api, chat_id))[1]["content"] == ""
    assert (await read(api, root))["chat_id"] == str(chat_id)

    api.gateway.proposal = "not json"
    failed = await start_in_chat(api, chat_id)
    assert await job(api, failed["root_id"]) == "completed"
    result = await read(api, failed["root_id"])
    assert result["status"] == "failed" and result["stop_reason"] == "invalid_proposal"
    thread = await messages(api, chat_id)
    assert [m["content"] for m in thread if m["kind"] == "run"] == ["", ""]
    async with api.env.factory() as db:
        rows = await db.scalars(
            select(WorkProductAttribution.id).where(WorkProductAttribution.chat_id == chat_id)
        )
        assert not rows.all()  # no answer, so nothing to attest


async def test_a_proposal_larger_than_the_cap_can_fund_is_refused_as_unfunded(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    tasks = json.loads(api.gateway.proposal)["tasks"]
    api.gateway.proposal = json.dumps({"tasks": [*tasks, {**tasks[0], "topic": "A third task"}]})
    value = await start_in_chat(api, chat_id)
    assert value["planning"]["max_children"] == 2
    assert await job(api, value["root_id"]) == "completed"
    # The planner was told the limit.
    assert api.gateway.plan_inputs[0]["max_tasks"] == 2
    result = await read(api, value["root_id"])
    assert result["status"] == "failed" and result["stop_reason"] == "unfunded_plan"
    assert result["tree"] is None and result["spent_usd"] != "0.0000"


async def test_receipts_show_a_run_through_the_same_feed_as_an_ordinary_turn(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    final = await run_to_completion(api, value)
    root = value["root_id"]

    response = await api.client.get(f"{CHATS}/{chat_id}/receipts")
    assert response.status_code == 200, response.text
    events = response.json()
    kinds = {e["kind"] for e in events}
    assert {"message", "skill", "audit"} <= kinds

    run_events = [
        e for e in events if e["kind"] == "message" and e["detail"]["message_kind"] == "run"
    ]
    assert len(run_events) == 1
    assert run_events[0]["detail"]["autonomous_session_id"] == root
    assert run_events[0]["detail"]["prompt_tokens"] == 20 * len(api.gateway.requests)
    assert sorted(e["detail"]["skill_name"] for e in events if e["kind"] == "skill") == [
        "contract-qa",
        "orchestration-chat-demo",
    ]

    audits = [e for e in events if e["kind"] == "audit"]
    actions = [e["detail"]["action"] for e in audits]
    for expected in (
        "orchestration.planning_started",
        "orchestration.plan_saved",
        "orchestration.approved",
        "orchestration.children_admitted",
        "orchestration.effect_admitted",
        "orchestration.effect_completed",
        "orchestration.topic_delivered",
        "orchestration.root_delivered",
        # The chokepoint's own rows for the root and for each child session.
        "autonomous_session.tool_call",
    ):
        assert expected in actions, expected
    assert all(e["detail"]["message_id"] == value["message_id"] for e in audits)
    assert all(e["detail"]["run_root_id"] == root for e in audits)
    sessions = {e["detail"]["session_id"] for e in audits}
    children = {c["session_id"] for c in final["tree"]["children"]}
    assert children <= sessions and root in sessions
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)

    # Nothing a model wrote, and no document text, reaches the feed.
    feed = json.dumps(events)
    assert api.gateway.child_answer not in feed and api.gateway.synthesis_answer not in feed
    assert "Term and renewal" not in feed and "The agreement is needed." not in feed

    # The filter and the export use the same merged stream.
    only = await api.client.get(f"{CHATS}/{chat_id}/receipts", params={"event_kinds": "message"})
    assert {e["kind"] for e in only.json()} == {"message"}
    export = await api.client.get(f"{CHATS}/{chat_id}/receipts/export.jsonl")
    assert export.status_code == 200
    assert len(export.text.splitlines()) == len(events)


async def test_a_run_started_without_a_chat_still_runs_and_has_no_message(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    value = await start(api)
    assert value["chat_id"] is None and value["message_id"] is None
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    for child in planned["tree"]["plan"]["children"]:
        assert await job(api, root, child["dispatch_id"]) == "completed"
    assert await job(api, root) == "completed"
    assert (await read(api, root))["status"] == "completed"
    async with api.env.factory() as db:
        bound = select(Message.id).where(Message.autonomous_session_id == UUID(root))
        assert not (await db.scalars(bound)).all()


async def test_run_model_calls_appear_as_inference_events_pinned_to_the_run_message(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    await run_to_completion(api, value)

    # The gateway writes one routing-log row per call from the identifiers the
    # request carried. The provider is controlled here, so write the rows the
    # gateway would, from exactly what each run request sent.
    async with api.env.factory.begin() as db:
        for sent_chat, sent_message, purpose in api.gateway.correlations:
            assert sent_chat == str(chat_id) and sent_message == value["message_id"]
            db.add(
                InferenceRoutingLog(
                    chat_id=UUID(sent_chat),
                    message_id=UUID(sent_message),
                    requested_model="selected/native",
                    routed_provider="selected",
                    routed_model="native",
                    routed_inference_tier=1,
                    tokens_in=20,
                    tokens_out=30,
                    latency_ms=5,
                    anonymization_applied=True,
                    purpose=purpose,
                )
            )
    events = (await api.client.get(f"{CHATS}/{chat_id}/receipts")).json()
    # The four kinds an ordinary answered turn produces, now for a run.
    assert {"message", "skill", "inference", "audit"} <= {e["kind"] for e in events}
    calls = [e for e in events if e["kind"] == "inference"]
    assert len(calls) == len(api.gateway.requests)
    for call in calls:
        assert call["detail"]["message_id"] == value["message_id"]
        assert call["detail"]["provider"] == "selected" and call["detail"]["tier"] == 1
        assert call["detail"]["anonymization_applied"] is True
    async with api.env.factory.begin() as db:
        await db.execute(delete(InferenceRoutingLog).where(InferenceRoutingLog.chat_id == chat_id))
