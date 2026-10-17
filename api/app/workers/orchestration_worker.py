"""Short arq invocations and bounded recovery for operator-enabled run profiles."""

import asyncio
from typing import Any
from uuid import UUID

from opentelemetry.context import Context
from opentelemetry.propagate import extract
from sqlalchemy import select

from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.watchdog import sweep_recovery
from app.errors import Conflict, Forbidden, NotFound
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationRoot as Root
from app.observability_helpers import get_tracer, quiet_span, record_attributes
from app.workers.queue import enqueue_orchestration_job

_tracer = get_tracer(__name__)


def _enabled(runtime: DemonstrationService | None) -> bool:
    """True when the operator has switched on at least one run profile."""
    if runtime is None:
        return False
    settings = runtime.settings
    return bool(
        getattr(settings, "orchestration_enabled", False)
        or getattr(settings, "orchestration_chat_enabled", False)
    )


async def wake_tree(runtime: DemonstrationService, root_id: UUID) -> int:
    async with runtime.store.sessions() as db:
        rows = list(
            await db.execute(
                select(AutonomousSession.id)
                .join(Root, Root.session_id == AutonomousSession.root_session_id)
                .where(
                    Root.session_id == root_id,
                    Root.status.in_(["planning", "queued", "running", "waiting_children"]),
                    AutonomousSession.status == "running",
                )
                .order_by(AutonomousSession.delegation_depth.desc(), AutonomousSession.child_order)
            )
        )
    async with runtime.store.sessions() as db:
        root = await db.get(Root, root_id)
        if root is None:
            return 0
        try:
            if runtime.for_profile(root.profile).policy() is None:
                return 0
        except Forbidden:
            # An unregistered or misconfigured profile wakes nothing.
            return 0
    for (session_id,) in rows:
        await enqueue_orchestration_job(root_id, session_id)
    return len(rows)


async def orchestration_session_job(
    ctx: dict[str, Any], root_id: str, session_id: str, trace: dict[str, str] | None = None
) -> dict[str, str]:
    """Run one session of a governed run for a short, claimed invocation.

    ``trace`` is the W3C trace context of whatever queued this job: the API
    request that accepted or approved the run, or the worker invocation that
    woke the tree. The job's span continues that trace, so a run is followed
    from the request through the worker to the gateway and provider
    (ADR 0038 D2). It carries identifiers only and grants nothing.
    """
    runtime: DemonstrationService | None = ctx.get("orchestration_runtime")
    if not _enabled(runtime):
        return {"status": "disabled"}
    assert runtime is not None
    root, session = UUID(root_id), UUID(session_id)
    with quiet_span(_tracer, "orchestration.job", context=_parent(trace)) as span:
        record_attributes(
            span,
            **{"orchestration.root_id": root_id, "orchestration.session_id": session_id},
        )
        status = await _run_job(runtime, root, session)
        # Every way a job ends is recorded, so a trace tells a stop from a run.
        record_attributes(span, **{"orchestration.outcome": status})
        return {"status": status}


def _parent(trace: object) -> Context | None:
    """The queued trace context, or none. A malformed carrier starts a new trace."""
    if not isinstance(trace, dict):
        return None
    carrier = {k: v for k, v in trace.items() if isinstance(k, str) and isinstance(v, str)}
    try:
        return extract(carrier)
    except Exception:
        return None


async def _run_job(runtime: DemonstrationService, root: UUID, session: UUID) -> str:
    try:
        async with runtime.store.sessions() as db:
            stored = await db.get(Root, root)
            if stored is None:
                return "stopped"
            runtime = runtime.for_profile(stored.profile)
        if runtime.policy() is None:
            return "disabled"
        result = await runtime.executor().run_one(root, session)
    except (Conflict, Forbidden, NotFound):
        # Duplicate/stale claims and stopped authority cannot start a new call.
        # The sweep resolves lease/deadline recovery; no exception text is logged.
        return "stopped"
    except Exception:
        # An interrupted checkpoint/phase is retried from durable continuation
        # by the bounded sweep. Raw exceptions never enter arq result logs.
        return "interrupted"
    if result in {"completed", "waiting_children"}:
        await wake_tree(runtime, root)
    return result


async def orchestration_watchdog(ctx: dict[str, Any]) -> dict[str, Any]:
    runtime: DemonstrationService | None = ctx.get("orchestration_runtime")
    if not _enabled(runtime):
        return {"status": "disabled"}
    assert runtime is not None
    # Recovery only narrows authority, so it covers every profile's roots;
    # work is woken only for a profile whose switch is on (see wake_tree).
    page = await sweep_recovery(runtime.store, after=ctx.get("orchestration_recovery_after"))
    ctx["orchestration_recovery_after"] = page.next_after
    woken = 0
    async with asyncio.timeout(5), runtime.store.sessions() as db:
        query = select(Root.session_id).where(
            Root.status.in_(["planning", "queued", "running", "waiting_children"]),
            Root.profile != "demonstration",
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
