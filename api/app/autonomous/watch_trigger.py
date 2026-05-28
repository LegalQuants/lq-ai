"""KB-arrival watch trigger — M4-B4.

When a file is attached to a watched knowledge base
(:func:`app.api.knowledge_bases.attach_file`), this module spawns one
autonomous session per enabled :class:`~app.models.autonomous.AutonomousWatch`
on that KB. The "doc arrives in a watched KB" event is the **attach**, not
ingest: :func:`attach_file` requires ``ingestion_status=='ready'`` (set only
at the end of ``ingest_file``), so at ingest time the file is in zero KBs and
a hook there would never fire.

The core logic lives in :func:`fire_watches_for_kb` with an injectable
``enqueue`` parameter (default the real
:func:`~app.workers.queue.enqueue_autonomous_session_job`), mirroring the
B3 schedule sweep (:func:`app.workers.autonomous_worker._run_schedule_sweep`)
so tests can drive it directly via the conftest SAVEPOINT session with a
stub enqueue.

The session is owned by ``watch.user_id`` — NOT the user who attached the
file. In practice the KB owner is the attacher (a watch can only target a KB
its creator owns), but ownership is taken from the watch unconditionally so
the autonomous layer's hard per-user isolation holds regardless of trigger
path.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.models.autonomous import AutonomousSession, AutonomousWatch
from app.models.user import User
from app.workers.queue import enqueue_autonomous_session_job

logger = logging.getLogger(__name__)


async def fire_watches_for_kb(
    db: Any,  # AsyncSession — typed as Any to match the worker-sweep idiom
    *,
    kb_id: uuid.UUID,
    file_id: uuid.UUID,
    enqueue: Callable[[uuid.UUID], Awaitable[bool]] | None = None,
) -> int:
    """Spawn one autonomous session per enabled watch on ``kb_id``.

    Called by :func:`app.api.knowledge_bases.attach_file` (best-effort,
    after the attach is committed) and directly by tests (with the
    conftest SAVEPOINT session and a stub ``enqueue``).

    For each :class:`~app.models.autonomous.AutonomousWatch` with
    ``knowledge_base_id == kb_id AND enabled AND deleted_at IS NULL``
    (the scan served by ``idx_autonomous_watches_kb_enabled``), it:

    1. Creates an :class:`~app.models.autonomous.AutonomousSession` owned
       by ``watch.user_id`` with ``trigger_kind='watch'``, ``trigger_ref``
       = the watch id, ``status='running'``, ``current_phase='intake'``,
       and ``params`` carrying the non-null subset of ``{"kb_id",
       "playbook_id", "skill_ref", "file_id"}``.
    2. Commits once after all session rows are created.
    3. ``await enqueue(session.id)`` for each created session — best-effort;
       the helper swallows transport errors and returns bool, and the loop
       is additionally wrapped so one bad enqueue does not stop the others.
       An orphaned ``running`` session whose enqueue failed is reaped by the
       idle watchdog (consistent with B3).

    Returns the count of sessions spawned.
    """

    enqueue_fn = enqueue if enqueue is not None else enqueue_autonomous_session_job
    settings = get_settings()

    watches_stmt = (
        select(AutonomousWatch)
        .join(User, User.id == AutonomousWatch.user_id)
        .where(
            AutonomousWatch.knowledge_base_id == kb_id,
            AutonomousWatch.enabled.is_(True),
            AutonomousWatch.deleted_at.is_(None),
            User.autonomous_enabled.is_(True),
        )
    )
    watches = (await db.execute(watches_stmt)).scalars().all()

    created: list[AutonomousSession] = []
    for watch in watches:
        # Build the trigger→target params carrying only the non-null keys.
        params: dict[str, Any] = {
            "kb_id": str(kb_id),
            "file_id": str(file_id),
        }
        if watch.playbook_id is not None:
            params["playbook_id"] = str(watch.playbook_id)
        if watch.skill_ref is not None:
            params["skill_ref"] = watch.skill_ref

        session = AutonomousSession(
            user_id=watch.user_id,
            project_id=watch.project_id,
            trigger_kind="watch",
            trigger_ref=watch.id,
            status="running",
            current_phase="intake",
            # Per-trigger cap when set, else the config default; never None
            # so R4 (economic brake) can trip on every spawned session.
            max_cost_usd=watch.max_cost_usd
            if watch.max_cost_usd is not None
            else settings.autonomous_default_max_cost_usd,
            params=params,
        )
        db.add(session)
        await db.flush()
        created.append(session)

    await db.commit()

    for session in created:
        # Best-effort: the helper already swallows transport errors and
        # returns bool, but wrap the loop so one bad enqueue cannot stop the
        # others. A session left at 'running' is reaped by the idle watchdog.
        try:
            await enqueue_fn(session.id)
        except Exception as exc:
            logger.warning(
                "fire_watches_for_kb: enqueue failed; session stays running",
                extra={
                    "event": "autonomous_watch_enqueue_failed",
                    "session_id": str(session.id),
                    "error_type": type(exc).__name__,
                },
            )

    logger.info(
        "fire_watches_for_kb: watches fired",
        extra={
            "event": "autonomous_watch_fired",
            "kb_id": str(kb_id),
            "file_id": str(file_id),
            "count": len(created),
        },
    )
    return len(created)
