"""Short arq invocations and bounded recovery for the opt-in demonstration."""

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.watchdog import sweep_recovery
from app.errors import Conflict, Forbidden, NotFound
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationRoot as Root
from app.workers.queue import enqueue_orchestration_job


async def wake_tree(runtime: DemonstrationService, root_id: UUID) -> int:
    async with runtime.store.sessions() as db:
        rows = list(
            await db.execute(
                select(AutonomousSession.id)
                .join(Root, Root.session_id == AutonomousSession.root_session_id)
                .where(
                    Root.session_id == root_id,
                    Root.status.in_(["queued", "running", "waiting_children"]),
                    AutonomousSession.status == "running",
                )
                .order_by(AutonomousSession.delegation_depth.desc(), AutonomousSession.child_order)
            )
        )
    for (session_id,) in rows:
        await enqueue_orchestration_job(root_id, session_id)
    return len(rows)


async def orchestration_session_job(
    ctx: dict[str, Any], root_id: str, session_id: str
) -> dict[str, str]:
    runtime: DemonstrationService | None = ctx.get("orchestration_runtime")
    if runtime is None or runtime.policy() is None:
        return {"status": "disabled"}
    root, session = UUID(root_id), UUID(session_id)
    try:
        result = await runtime.executor().run_one(root, session)
    except (Conflict, Forbidden, NotFound):
        # Duplicate/stale claims and stopped authority cannot start a new call.
        # The sweep resolves lease/deadline recovery; no exception text is logged.
        return {"status": "stopped"}
    except Exception:
        # An interrupted checkpoint/phase is retried from durable continuation
        # by the bounded sweep. Raw exceptions never enter arq result logs.
        return {"status": "interrupted"}
    if result in {"completed", "waiting_children"}:
        await wake_tree(runtime, root)
    return {"status": result}


async def orchestration_watchdog(ctx: dict[str, Any]) -> dict[str, Any]:
    runtime: DemonstrationService | None = ctx.get("orchestration_runtime")
    if runtime is None or runtime.policy() is None:
        return {"status": "disabled"}
    page = await sweep_recovery(runtime.store, after=ctx.get("orchestration_recovery_after"))
    ctx["orchestration_recovery_after"] = page.next_after
    woken = 0
    async with asyncio.timeout(5), runtime.store.sessions() as db:
        query = select(Root.session_id).where(
            Root.status.in_(["queued", "running", "waiting_children"])
        )
        after = ctx.get("orchestration_wakeup_after")
        if after is not None:
            query = query.where(Root.session_id > after)
        roots = list(await db.scalars(query.order_by(Root.session_id).limit(26)))
    # A queue failure leaves durable state for the next pass. Bound this
    # job so unavailable Redis does not consume an entire invocation.
    try:
        async with asyncio.timeout(15):
            for root_id in roots[:25]:
                # Advance only over attempted roots. A slow/failed queue
                # must not starve later roots by skipping the whole page.
                ctx["orchestration_wakeup_after"] = root_id
                woken += await wake_tree(runtime, root_id)
            if len(roots) <= 25:
                ctx["orchestration_wakeup_after"] = None
    except TimeoutError:
        pass
    return {
        "inspected": page.inspected,
        "claims_recovered": page.claims_recovered,
        "roots_expired": page.roots_expired,
        "failures": len(page.failures),
        "woken": woken,
    }
