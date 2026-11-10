"""ADR 0038 D6: an owner can close an uncertain run.

ADR 0035 D5 stands: nothing is repeated. Closing ends the run without
synthesis, keeps retained work readable, converts each unresolved reservation
into a charge, writes an audit row and releases the owner's active-run
allowance.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from tests.autonomous.orchestration.model_harness import (
    BASE,
    CHATS,
    approve,
    job,
    messages,
    new_chat,
    read,
    run_to_completion,
    start_in_chat,
)

from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
)
from app.models.user import User

pytestmark = pytest.mark.integration


async def close(api: SimpleNamespace, root: str, expect: int = 200) -> dict:
    response = await api.client.post(f"{BASE}/chat-runs/{root}/close")
    assert response.status_code == expect, response.text
    return response.json()


async def fictional(api: SimpleNamespace, chat_id: object) -> tuple[dict, dict | None]:
    value = (await api.client.get(f"{CHATS}/{chat_id}/run-profiles")).json()
    return next(p for p in value["profiles"] if p["profile"] == "model_demo_v1"), value[
        "active_run"
    ]


async def test_closing_an_uncertain_planning_call_charges_it_and_frees_the_allowance(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    api.gateway.uncertain = True
    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    await job(api, root)
    stuck = await read(api, root)
    assert stuck["status"] == "uncertain" and stuck["effects"][0]["status"] == "uncertain"
    reserved = Decimal(stuck["reserved_usd"])
    assert reserved > 0 and Decimal(stuck["spent_usd"]) == 0

    # The composer names the run that is blocking a new one, and a start is refused.
    profile, active = await fictional(api, chat_id)
    assert profile["reason"] == "active_run"
    assert active is not None
    assert active == {
        "root_id": root,
        "status": "uncertain",
        "profile": "model_demo_v1",
        "chat_id": str(chat_id),
        "chat_title": active["chat_title"],
        "message_id": value["message_id"],
    }
    await start_in_chat(api, chat_id, expect=409)
    # Halt does not resolve uncertainty: the run still holds the allowance.
    halted = await api.client.post(f"{BASE}/chat-runs/{root}/halt")
    assert halted.json()["status"] == "uncertain"

    sent = len(api.gateway.requests)
    closed = await close(api, root)
    assert closed["status"] == "closed" and closed["stop_reason"] == "owner_closed"
    assert Decimal(closed["reserved_usd"]) == 0
    assert Decimal(closed["spent_usd"]) == reserved
    assert closed["effects"][0]["status"] == "closed"
    assert Decimal(closed["effects"][0]["charged_usd"]) == reserved
    assert closed["tree"] is None  # planning never produced a plan
    # Nothing was repeated to get here.
    assert len(api.gateway.requests) == sent

    async with api.env.factory() as db:
        effect = await db.get(Effect, (UUID(root), "chat:plan:v1"))
        assert effect is not None and effect.status == "closed"
        assert effect.result is None and effect.completed_at is not None
        account = await db.get(Account, UUID(root))
        assert account is not None and account.worker_id is None
        session = await db.get(AutonomousSession, UUID(root))
        assert session is not None and session.status == "halted"
        assert session.cost_total_usd == reserved
        audit = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.resource_id == root, AuditLog.action == "orchestration.run_closed"
                )
            )
        ).one()
        assert audit.details == {"effects_closed": 1, "charged_usd": format(reserved, ".4f")}
        assert audit.user_id == api.env.owner_id

    # The message stays empty, and closing twice changes nothing.
    assert (await messages(api, chat_id))[1]["content"] == ""
    assert (await close(api, root))["spent_usd"] == closed["spent_usd"]
    async with api.env.factory() as db:
        rows = await db.scalars(
            select(AuditLog).where(
                AuditLog.resource_id == root, AuditLog.action == "orchestration.run_closed"
            )
        )
        assert len(rows.all()) == 1

    # A new run can start, and it completes.
    profile, active = await fictional(api, chat_id)
    assert profile["available"] is True and active is None
    api.gateway.uncertain = False
    again = await start_in_chat(api, chat_id)
    assert (await run_to_completion(api, again))["status"] == "completed"
    # The closed run's worker can never be woken into a call.
    assert await job(api, root) == "stopped"


async def test_closing_keeps_completed_child_work_and_charges_only_what_is_unresolved(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    first, second = (c["dispatch_id"] for c in planned["tree"]["plan"]["children"])
    assert await job(api, root, first) == "completed"

    # The second child's provider call never returns a trustworthy outcome.
    api.gateway.uncertain_operations = {"answer_contract_question"}
    await job(api, root, second)
    stuck = await read(api, root)
    assert stuck["status"] == "uncertain"
    done, lost = stuck["tree"]["children"]
    assert done["outcome"]["status"] == "completed" and lost["outcome"] is None
    reserved = Decimal(lost["reserved_usd"])
    assert reserved > 0 and Decimal(done["reserved_usd"]) == 0
    spent_before = Decimal(stuck["spent_usd"])

    # No job can make progress, and none retries the lost call.
    sent = len(api.gateway.requests)
    for session in (second, root):
        assert await job(api, root, session) == "stopped"
    assert len(api.gateway.requests) == sent

    closed = await close(api, root)
    assert closed["status"] == "closed"
    assert Decimal(closed["reserved_usd"]) == 0
    assert Decimal(closed["spent_usd"]) == spent_before + reserved
    done, lost = closed["tree"]["children"]
    # Retained work stays inspectable: the finished answer and its files.
    assert done["outcome"]["status"] == "completed" and done["files"]
    assert lost["status"] == "halted"
    assert [e["status"] for e in lost["effects"] if e["effect_key"] == "topic:t1"] == ["closed"]
    assert closed["tree"]["result"] is None and "stopped" in closed["tree"]["partial_summary"]
    file = await api.client.get(f"{BASE}/{root}/files/{done['session_id']}/findings.json")
    assert file.status_code == 200 and json.loads(file.json()["content"])["status"] == "completed"
    assert (await messages(api, chat_id))[1]["content"] == ""

    async with api.env.factory() as db:
        child = await db.get(AutonomousSession, UUID(second))
        assert child is not None and child.status == "halted"
        # Only the unresolved call was charged on closing.
        other = await db.get(Account, UUID(first))
        assert other is not None and other.spent_usd == Decimal(done["spent_usd"])


async def test_only_the_owner_can_close_and_only_an_uncertain_run(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    await close(api, root, expect=409)  # planning
    assert await job(api, root) == "completed"
    await close(api, root, expect=409)  # awaiting approval
    final = await run_to_completion_from_planned(api, root)
    assert final["status"] == "completed"
    await close(api, root, expect=409)  # completed
    await close(api, str(uuid4()), expect=404)

    api.gateway.uncertain = True
    stuck = await start_in_chat(api, chat_id)
    await job(api, stuck["root_id"])
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
        await close(api, stuck["root_id"], expect=404)
    finally:
        api.user.id = owner_id
        async with api.env.factory.begin() as db:
            await db.execute(delete(User).where(User.id == stranger_id))
    assert (await read(api, stuck["root_id"]))["status"] == "uncertain"

    # Closing stays reachable after the owner opts out and the profile is switched off.
    api.user.autonomous_enabled = False
    api.runtime.settings.orchestration_chat_enabled = False
    assert (await close(api, stuck["root_id"]))["status"] == "closed"


async def run_to_completion_from_planned(api: SimpleNamespace, root: str) -> dict:
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    for child in planned["tree"]["plan"]["children"]:
        assert await job(api, root, child["dispatch_id"]) == "completed"
    assert await job(api, root) == "completed"
    return await read(api, root)
