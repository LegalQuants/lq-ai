"""Audit-log writer — Task D3.

Per PRD §5.3: "Every state-changing API call writes to an
``audit_log`` table." This module centralises the shape of those
writes so:

* every call site populates ``privilege_marked`` and
  ``privilege_basis`` consistently — based on the affected
  project's ``privileged`` flag rather than ad-hoc per-handler
  reasoning;
* request context (``ip_address``, ``user_agent``, ``request_id``)
  is captured uniformly when the caller hands us the ``Request``;
* ``routed_inference_tier`` lands on inference-touching audit rows
  via the same code path as everything else.

The expected callsite shape is::

    from app.audit import audit_action

    await audit_action(
        db,
        user_id=user.id,
        action="project.create",
        resource_type="project",
        resource_id=str(project.id),
        project=project,
        request=request,
        details={"name": project.name, "privileged": project.privileged},
    )

The handler still calls ``await db.commit()`` afterwards — this
helper inserts the row and flushes but does not commit, so audit
writes ride the same transaction as the state change they describe
(no audit-row-without-state-change and no state-change-without-
audit-row failure modes).

Privilege resolution
--------------------

When ``project`` is provided as a :class:`Project` instance, the
helper reads ``project.privileged`` and ``project.id`` directly. When
only ``project_id`` is provided, the helper does a one-row lookup. If
neither is provided, the action is non-privilege-relevant and the
fields stay null/false (e.g., ``user.login`` has no project context).

Callers can also pass ``privilege_marked`` and ``privilege_basis``
explicitly when the action is privilege-bearing for a non-project
reason (e.g., admin-action audits in PRD §5.3 ¶"Role-bounded admin
actions audit").
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.project import Project
from app.security.client_ip import resolve_client_ip

if TYPE_CHECKING:
    pass


def _client_metadata(request: Request | None) -> tuple[str | None, str | None, str | None]:
    """Pull (ip_address, user_agent, request_id) off a Request, all nullable."""

    if request is None:
        return None, None, None

    user_agent = request.headers.get("user-agent")
    ip_address = resolve_client_ip(request, get_settings().lq_ai_trusted_proxies)
    # The B5 GatewayClient + chat handler stamp X-Request-ID; the
    # FastAPI middleware (when present) uses the same header. Read
    # it opportunistically so audit rows correlate to log lines.
    request_id = request.headers.get("x-request-id")
    return ip_address, user_agent, request_id


async def _resolve_project_privilege(
    db: AsyncSession,
    *,
    project: Project | None,
    project_id: uuid.UUID | None,
) -> tuple[bool, str | None]:
    """Return ``(privilege_marked, privilege_basis)`` for an audited action.

    The basis is the project's name (a stable, human-readable
    handle); a future task can replace it with the matter or
    instruction reference once that surface exists. The basis is
    only set when the project is privileged, matching the DB CHECK
    constraint ``chk_audit_log_privileged_with_basis``.
    """

    if project is None and project_id is None:
        return False, None

    if project is None and project_id is not None:
        project = await db.get(Project, project_id)
        if project is None:
            return False, None

    assert project is not None  # narrowed for the type checker
    if not project.privileged:
        return False, None

    return True, f"project:{project.name}"


async def audit_action(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    project: Project | None = None,
    project_id: uuid.UUID | None = None,
    privilege_marked: bool | None = None,
    privilege_basis: str | None = None,
    routed_inference_tier: int | None = None,
    routed_provider: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    timestamp: Any | None = None,
) -> AuditLog:
    """Insert one ``audit_log`` row for ``action``; return the inserted instance.

    The row is added to ``db`` and flushed but not committed — the
    caller's outer transaction owns the commit so the audit row
    rides the same boundary as the state change.
    """

    if privilege_marked is None or privilege_basis is None:
        resolved_marked, resolved_basis = await _resolve_project_privilege(
            db, project=project, project_id=project_id
        )
        if privilege_marked is None:
            privilege_marked = resolved_marked
        if privilege_basis is None:
            privilege_basis = resolved_basis

    ip_address, user_agent, request_id = _client_metadata(request)

    row = AuditLog(
        # Ordinary audit rows retain their existing transaction-time default.
        **({"timestamp": timestamp} if timestamp is not None else {}),
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        privilege_marked=privilege_marked,
        privilege_basis=privilege_basis,
        routed_inference_tier=routed_inference_tier,
        routed_provider=routed_provider,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        details=details,
    )
    db.add(row)
    await db.flush()
    return row
