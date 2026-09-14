"""Bounded recovery sweeps; deliberately not registered with production arq.

Pagination is maintenance scan state, not graph continuation or retry authority.
The caller follows next_after until None, then starts a new scan from the start.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import exists, or_, select

from app.autonomous.orchestration.store import OrchestrationStore
from app.errors import Conflict, NotFound, ValidationError
from app.models.orchestration import OrchestrationAccount as Account, OrchestrationRoot as Root


@dataclass(frozen=True)
class RecoveryFailure:
    root_id: UUID
    stage: Literal["claims", "deadline"]
    code: Literal["timeout", "not_found", "conflict", "internal_error"]


@dataclass(frozen=True)
class RecoverySweep:
    """Confirmed stage counts and IDs; no plan, receipt or exception content.

    claims_recovered counts the claim stage only: deadline recovery may also
    drain ownership. A timeout may leave an unacknowledged commit, so these are
    sweep diagnostics, not authoritative ledger totals. Retry from durable state.
    """

    inspected: int
    claims_recovered: int
    roots_expired: int
    failures: tuple[RecoveryFailure, ...]
    next_after: UUID | None


async def sweep_recovery(
    store: OrchestrationStore,
    *,
    after: UUID | None = None,
    limit: int = 25,
    operation_timeout_seconds: int = 2,
) -> RecoverySweep:
    """Process one page with isolated, independently committed recovery stages.

    Discovery reads IDs only and closes its transaction before recovery. Each
    operation rechecks live database state. Failure of one stage does not undo a
    previously committed stage or block later roots. Cancellation propagates;
    replaying a page relies on the store's idempotent recovery, not a second cursor
    for execution. The timeout bounds each discovery/recovery await, not hard
    wall-clock duration of database cancellation cleanup.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValidationError(message="Recovery page size must be between 1 and 50")
    if type(operation_timeout_seconds) is not int or not 1 <= operation_timeout_seconds <= 5:
        raise ValidationError(message="Recovery operation timeout must be between 1 and 5 seconds")
    if after is not None and not isinstance(after, UUID):
        raise ValidationError(message="Recovery cursor must be a root UUID")
    owned = exists(
        select(Account.session_id).where(
            Account.root_id == Root.session_id, Account.worker_id.is_not(None)
        )
    )
    stmt = select(Root.session_id).where(
        or_(
            Root.status.in_(
                ["awaiting_approval", "queued", "running", "waiting_children", "uncertain"]
            ),
            owned,
        )
    )
    if after is not None:
        stmt = stmt.where(Root.session_id > after)
    async with asyncio.timeout(operation_timeout_seconds), store.sessions() as db:
        ids = list((await db.scalars(stmt.order_by(Root.session_id).limit(limit + 1))).all())
    page = ids[:limit]
    recovered = expired = 0
    failures: list[RecoveryFailure] = []
    for root_id in page:
        # Claim cleanup stays available even when plan validation fails. These
        # are separate transactions, so a deadline failure may follow a committed
        # claim cleanup; report both outcomes rather than pretending atomicity.
        for stage in ("claims", "deadline"):
            try:
                async with asyncio.timeout(operation_timeout_seconds):
                    if stage == "claims":
                        recovered += await store.recover_expired_claims(root_id)
                    else:
                        expired += int(await store.expire_root(root_id))
            except Exception as exc:
                # Do not include exception text, SQL parameters or traceback: a
                # policy/validation failure may contain private application data.
                code: Literal["timeout", "not_found", "conflict", "internal_error"]
                if isinstance(exc, TimeoutError):
                    code = "timeout"
                elif isinstance(exc, NotFound):
                    code = "not_found"
                elif isinstance(exc, Conflict):
                    code = "conflict"
                else:
                    code = "internal_error"
                failures.append(RecoveryFailure(root_id, stage, code))
    return RecoverySweep(
        len(page), recovered, expired, tuple(failures), page[-1] if len(ids) > limit else None
    )
