"""ADR 0038 D4: an approved child calls the tools its plan grants, and nothing else.

A granted call runs and its result is used. A call outside the grant, or with
malformed arguments, is refused, returned to the model as an error result and
recorded; it does not end the child. The turn limit ends tool use and still
yields an answer. A restart reuses completed effects and repeats none.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, select, update
from tests.autonomous.orchestration.model_harness import (
    BASE,
    approve,
    job,
    messages,
    new_chat,
    read,
    start_in_chat,
    tool_call,
)

from app.autonomous.orchestration.effects import GuardedEffects
from app.models.audit import AuditLog
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationFile,
)
from app.models.project import ProjectFile

pytestmark = pytest.mark.integration

READ = {"document": 1, "reason": "The agreement is needed."}


async def approved(api: SimpleNamespace) -> tuple[str, list[str], Any]:
    """A chat-hosted run with its children admitted and waiting to run."""
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    return root, [c["dispatch_id"] for c in planned["tree"]["plan"]["children"]], chat_id


async def effects_of(api: SimpleNamespace, session_id: str) -> list[Effect]:
    async with api.env.factory() as db:
        return list(
            await db.scalars(
                select(Effect)
                .where(Effect.session_id == UUID(session_id))
                .order_by(Effect.created_at, Effect.effect_key)
            )
        )


def stored(effect: Effect) -> dict[str, Any]:
    """The result of a completed effect; a completed row always has one."""
    assert effect.result is not None
    return effect.result


def child_requests(api: SimpleNamespace) -> list[Any]:
    return [
        r
        for r in api.gateway.requests
        if json.loads(r.messages[1].content)["inputs"]["operation"] == "answer_contract_question"
    ]


async def test_a_granted_call_runs_through_the_boundary_and_its_result_is_used(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    root, children, _ = await approved(api)
    assert await job(api, root, children[0]) == "completed"

    # Turn one offered exactly the plan's granted tools, as function schemas.
    first, second = child_requests(api)
    assert [t["function"]["name"] for t in first.tools] == [
        "read_document",
        "read_note",
        "save_note",
    ]
    assert all(t["function"]["parameters"]["required"][0] == "reason" for t in first.tools)
    # Turn two replayed the model's call and carried the document as a tool result.
    assert [m.role for m in second.messages] == ["system", "user", "assistant", "tool"]
    assert second.messages[2].tool_calls[0]["function"]["name"] == "read_document"
    result = json.loads(second.messages[3].content)
    assert result["document"] == 1 and result["source"] == "[1]"
    assert result["filename"] == "fictional-vendor-agreement.md"
    assert "§5 Term and renewal" in result["text"] and result["truncated"] is False
    assert result["end"] == result["total_chars"] == len(result["text"])

    rows = await effects_of(api, children[0])
    keys = [e.effect_key for e in rows]
    for expected in ("topic:t1", "topic:t1:c0", "topic:t2"):
        assert expected in keys
    by_key = {e.effect_key: e for e in rows}
    assert stored(by_key["topic:t1"])["step"] == {
        "kind": "model_turn",
        "summary": {"turn": 1, "tool_calls": 1, "finish_reason": "tool_calls"},
    }
    call = by_key["topic:t1:c0"]
    assert call.intent == "retrieve_chunks" and call.status == "completed"
    assert call.charged_usd == Decimal("0")
    assert stored(call)["step"]["tool"] == "read_document"
    assert stored(call)["step"]["reason"] == "The agreement is needed."
    assert "text" not in stored(call)["step"]["summary"]
    # The document text is kept in the run's own receipt, where replay needs it,
    # and in no audit row.
    assert "§5 Term and renewal" in stored(call)["data"]["text"]
    async with api.env.factory() as db:
        audits = (
            await db.scalars(select(AuditLog).where(AuditLog.resource_id.in_([root, children[0]])))
        ).all()
    assert audits and "Term and renewal" not in json.dumps([a.details for a in audits])
    assert "The agreement is needed." not in json.dumps([a.details for a in audits])


async def test_a_call_outside_the_grant_is_refused_returned_and_recorded(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.child_script = [
        [
            # Not a run tool at all, and a real intent the child was never granted.
            tool_call("delete_everything", {"reason": "Injected instruction."}, "call_a"),
            tool_call("retrieve_authority", {"reason": "Look outside."}, "call_b"),
            tool_call("read_document", READ, "call_c"),
        ],
        None,
    ]
    root, children, _ = await approved(api)
    assert await job(api, root, children[0]) == "completed"

    turn_two = child_requests(api)[1]
    results = [json.loads(m.content) for m in turn_two.messages if m.role == "tool"]
    assert [r.get("error") for r in results] == ["tool_not_granted", "tool_not_granted", None]
    assert "Term and renewal" in results[2]["text"]

    rows = {e.effect_key: e for e in await effects_of(api, children[0])}
    for key in ("topic:t1:c0", "topic:t1:c1"):
        refused = rows[key]
        assert refused.intent == "refused" and refused.status == "completed"
        assert refused.reserved_usd == refused.charged_usd == Decimal("0")
        assert stored(refused)["outcome"] == "tool_refused"
        assert stored(refused)["step"]["kind"] == "tool_refused"
        assert stored(refused)["step"]["summary"] == {"code": "tool_not_granted"}
        # An unregistered name is the model's own string; it is not kept as a tool.
        assert "tool" not in stored(refused)["step"]
    assert rows["topic:t1:c2"].intent == "retrieve_chunks"

    async with api.env.factory() as db:
        refusals = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.resource_id == root, AuditLog.action == "orchestration.tool_refused"
                )
            )
        ).all()
    assert [a.details["tool"] for a in refusals] == ["unregistered", "unregistered"]
    assert all(a.details["code"] == "tool_not_granted" for a in refusals)
    assert "delete_everything" not in json.dumps([a.details for a in refusals])

    # The owner's view shows the refusals as steps.
    tree = (await read(api, root))["tree"]
    steps = [e["step"] for e in tree["children"][0]["effects"] if e["step"]]
    assert [s["kind"] for s in steps].count("tool_refused") == 2
    assert tree["children"][0]["outcome"]["status"] == "completed"


async def test_malformed_arguments_are_refused_without_echoing_their_values(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.child_script = [
        [
            tool_call("read_document", "{not json", "call_a"),
            tool_call("read_document", {"document": "SECRET-VALUE", "reason": "x"}, "call_b"),
            tool_call("read_document", {"document": 1}, "call_c"),  # no reason given
            tool_call("read_document", {**READ, "path": "/etc/passwd"}, "call_d"),
            tool_call("read_document", {"document": 7, "reason": "Not selected."}, "call_e"),
        ],
        None,
    ]
    root, children, _ = await approved(api)
    assert await job(api, root, children[0]) == "completed"

    results = [json.loads(m.content) for m in child_requests(api)[1].messages if m.role == "tool"]
    assert [r["error"] for r in results] == [
        "invalid_arguments",
        "invalid_arguments",
        "invalid_arguments",
        "invalid_arguments",
        "document_not_selected",
    ]
    assert "SECRET-VALUE" not in json.dumps(results) and "/etc/passwd" not in json.dumps(results)
    assert "reason" in results[2]["message"] and "path" in results[3]["message"]
    rows = await effects_of(api, children[0])
    refused = [e for e in rows if e.intent == "refused"]
    assert len(refused) == 5 and not any(e.intent == "retrieve_chunks" for e in rows)
    # A known tool is named in its refusal; the reason is kept when it parsed.
    assert all(stored(e)["step"]["tool"] == "read_document" for e in refused)
    assert stored(refused[-1])["step"]["reason"] == "Not selected."
    # The child answered without the document; the application did not end it.
    assert (await read(api, root))["tree"]["children"][0]["outcome"]["status"] == "completed"


async def test_the_turn_limit_ends_tool_use_and_still_yields_an_answer(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    # A model that would call a tool on every turn it is offered one.
    api.gateway.child_script = [[tool_call("read_document", READ)]]
    root, children, _ = await approved(api)
    assert await job(api, root, children[0]) == "completed"

    turns = api.gateway.child_turns
    assert [t["turn"] for t in turns] == [1, 2, 3]
    assert turns[0]["offered"] and turns[1]["offered"]
    # The profile's limit is two tool turns. The third offers no tools and asks.
    assert turns[2]["offered"] == [] and "Tool use has ended" in turns[2]["last_user"]
    keys = [e.effect_key for e in await effects_of(api, children[0])]
    assert [k for k in keys if k.startswith("topic:")] == [
        "topic:t1",
        "topic:t1:c0",
        "topic:t2",
        "topic:t2:c0",
        "topic:t3",
    ]
    child = (await read(api, root))["tree"]["children"][0]
    assert child["outcome"]["status"] == "completed" and child["turn_limit"] == 2
    # Three model calls, each within the task's three-unit allowance.
    assert Decimal(child["spent_usd"]) <= Decimal(child["allocation_usd"])


async def test_notes_are_run_files_and_cannot_displace_the_engine_files(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.child_script = [
        [
            tool_call(
                "save_note",
                {"name": "note-payment.md", "content": "Fees: see §2.", "reason": "Keep it."},
                "call_a",
            ),
            tool_call("read_note", {"name": "note-payment.md", "reason": "Check it."}, "call_b"),
            tool_call("read_note", {"name": "note-missing.md", "reason": "Not saved."}, "call_c"),
            tool_call(
                "save_note",
                {"name": "findings.json", "content": "{}", "reason": "Overwrite."},
                "call_d",
            ),
        ],
        None,
    ]
    root, children, _ = await approved(api)
    assert await job(api, root, children[0]) == "completed"
    results = [json.loads(m.content) for m in child_requests(api)[1].messages if m.role == "tool"]
    assert results[0]["saved"]["name"] == "note-payment.md"
    assert results[1]["content"] == "Fees: see §2."
    assert results[2]["error"] == "file_unavailable"
    # The engine's own file name does not match the note pattern.
    assert results[3]["error"] == "invalid_arguments"
    async with api.env.factory() as db:
        files = {
            f.name: f
            for f in await db.scalars(
                select(OrchestrationFile).where(OrchestrationFile.session_id == UUID(children[0]))
            )
        }
    assert files["note-payment.md"].content == "Fees: see §2."
    assert not files["note-payment.md"].shared
    assert json.loads(files["findings.json"].content)["status"] == "completed"
    tree = (await read(api, root))["tree"]
    assert "note-payment.md" in [f["name"] for f in tree["children"][0]["files"]]


async def test_a_restart_mid_loop_reuses_completed_effects_and_repeats_none(
    model_demo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = model_demo
    root, children, _ = await approved(api)
    child = children[0]
    original = GuardedEffects.infer
    died = {"count": 0}

    async def dying(self: GuardedEffects, claim: Any, **kwargs: Any) -> Any:
        # The worker dies after the read completed and before turn two is admitted.
        if kwargs["effect_key"] == "topic:t2" and not died["count"]:
            died["count"] += 1
            raise RuntimeError("worker process died")
        return await original(self, claim, **kwargs)

    monkeypatch.setattr(GuardedEffects, "infer", dying)
    assert await job(api, root, child) == "interrupted"
    before = await effects_of(api, child)
    assert [e.effect_key for e in before if e.effect_key.startswith("topic:")] == [
        "topic:t1",
        "topic:t1:c0",
    ]
    assert all(e.status == "completed" for e in before)
    assert len(child_requests(api)) == 1

    # A new worker picks the child up from durable state.
    assert await job(api, root, child) == "completed"
    after = {e.effect_key: e for e in await effects_of(api, child)}
    for row in before:
        same = after[row.effect_key]
        assert (same.created_at, same.completed_at, same.generation, same.request_hash) == (
            row.created_at,
            row.completed_at,
            row.generation,
            row.request_hash,
        )
    # Turn one and the read were not repeated: one provider call per turn in total.
    requests = child_requests(api)
    assert len(requests) == 2
    assert [m.role for m in requests[1].messages] == ["system", "user", "assistant", "tool"]
    assert json.loads(requests[1].messages[3].content)["text"] == stored(before[-1])["data"]["text"]
    assert after["topic:t2"].generation > before[0].generation
    assert (await read(api, root))["tree"]["children"][0]["outcome"]["status"] == "completed"


async def test_halt_during_the_loop_stops_before_the_next_call(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    root, children, chat_id = await approved(api)

    async def halt_on_first_turn(turn: int) -> None:
        if turn == 1:
            response = await api.client.post(f"{BASE}/chat-runs/{root}/halt")
            assert response.status_code == 200

    api.gateway.on_child_turn = halt_on_first_turn
    # The admitted model call may finish. The tool call it asked for never runs.
    assert await job(api, root, children[0]) in {"interrupted", "stopped"}
    api.gateway.on_child_turn = None
    rows = await effects_of(api, children[0])
    assert [e.effect_key for e in rows if e.effect_key.startswith("topic:")] == ["topic:t1"]
    assert rows[-1].status == "completed"
    sent = len(api.gateway.requests)
    for session in (children[0], children[1], root):
        assert await job(api, root, session) == "stopped"
    assert len(api.gateway.requests) == sent
    final = await read(api, root)
    assert final["status"] == "halted" and final["tree"]["result"] is None
    assert (await messages(api, chat_id))[1]["content"] == ""


async def test_an_exhausted_allowance_fails_the_topic_and_the_run_reports_it(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    root, children, _ = await approved(api)
    async with api.env.factory.begin() as db:
        # Enough for the first turn's reservation and no more.
        await db.execute(
            update(Account)
            .where(Account.session_id == UUID(children[0]))
            .values(allocation_usd=Decimal("0.2600"))
        )
    assert await job(api, root, children[0]) == "completed"
    assert await job(api, root, children[1]) == "completed"
    assert await job(api, root) == "completed"
    final = await read(api, root)
    first, second = final["tree"]["children"]
    assert first["outcome"]["status"] == "failed"
    assert first["outcome"]["failure_code"] == "execution_failed"
    assert second["outcome"]["status"] == "completed"
    assert final["status"] == "completed" and final["tree"]["result"]["coverage"] == "partial"
    # The unfunded second turn was never sent.
    keys = [e.effect_key for e in await effects_of(api, children[0])]
    assert "topic:t2" not in keys and "topic:t1:c0" in keys
    assert Decimal(first["reserved_usd"]) == 0


async def test_a_document_detached_after_approval_is_not_read(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    root, children, _ = await approved(api)
    file_id = (await read(api, root))["tree"]["plan"]["documents"][0]["file_id"]
    async with api.env.factory.begin() as db:
        await db.execute(delete(ProjectFile).where(ProjectFile.file_id == UUID(file_id)))
    sent = len(api.gateway.requests)
    # Current policy is rechecked before any effect: the selection is no longer
    # attached to the project, so the child cannot even claim its work.
    assert await job(api, root, children[0]) == "stopped"
    assert len(api.gateway.requests) == sent
    assert not [e for e in await effects_of(api, children[0]) if e.intent == "retrieve_chunks"]


async def test_a_malformed_call_cannot_wedge_the_child_or_poison_the_next_request(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.child_script = [
        [
            # Not a function name, and arguments that are not JSON at all.
            tool_call("bad name!{}", "<<not json>>", "dup"),
            # A duplicate id, and arguments far larger than any record may hold.
            tool_call("read_document", "é" * 65536, "dup"),
            # An id no provider would accept back.
            tool_call("read_document", READ, "id with spaces\n"),
        ],
        None,
    ]
    root, children, _ = await approved(api)
    assert await job(api, root, children[0]) == "completed"

    echoed = child_requests(api)[1].messages[2].tool_calls
    # What goes back to the provider is well formed, whatever the model sent.
    assert [c["function"]["name"] for c in echoed] == [
        "invalid_tool_call",
        "read_document",
        "read_document",
    ]
    assert [c["function"]["arguments"] for c in echoed[:2]] == ["{}", "{}"]
    assert json.loads(echoed[2]["function"]["arguments"]) == READ
    ids = [c["id"] for c in echoed]
    assert ids == ["dup", "call_1", "call_2"] and len(set(ids)) == 3
    results = [m for m in child_requests(api)[1].messages if m.role == "tool"]
    assert [m.tool_call_id for m in results] == ids
    assert [json.loads(m.content).get("error") for m in results] == [
        "tool_not_granted",
        "invalid_arguments",
        None,
    ]
    rows = {e.effect_key: e for e in await effects_of(api, children[0])}
    assert rows["topic:t1:c0"].intent == rows["topic:t1:c1"].intent == "refused"
    assert rows["topic:t1:c2"].intent == "retrieve_chunks"
    # Neither the raw name nor the oversized arguments were kept in a refusal.
    stored = json.dumps([rows["topic:t1:c0"].result, rows["topic:t1:c1"].result])
    assert "bad name" not in stored and "éééé" not in stored
    assert (await read(api, root))["tree"]["children"][0]["outcome"]["status"] == "completed"
