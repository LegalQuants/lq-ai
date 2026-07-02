"""C5 (PR6d) — resolve which connectors a deployment has configured, so the
skill-detail endpoint can SURFACE (never enforce) a skill's declared
``tool_usage`` against reality."""

from __future__ import annotations

import logging

from app.mcp.service import list_servers
from app.research.service import get_capabilities

log = logging.getLogger(__name__)

_COURTLISTENER = "courtlistener"


async def resolve_available_connectors(*, request_id: str | None = None) -> set[str] | None:
    """The connector identifiers the operator has wired: CourtListener (when the
    gateway advertises it) union configured MCP server names. Returns ``None`` when
    availability can't be determined (gateway unreachable) — the caller treats
    ``None`` as 'unknown', NOT 'all missing'."""
    try:
        caps = await get_capabilities(request_id=request_id)
        servers = await list_servers(request_id=request_id)
    except Exception as exc:  # degrade to 'unknown', never 500 the skill view
        log.warning("resolve_available_connectors: capability probe failed: %r", exc)
        return None
    available: set[str] = set()
    if isinstance(caps, dict) and caps.get("enabled"):
        available.add(_COURTLISTENER)
    for s in servers or []:
        name = s.get("name") if isinstance(s, dict) else None
        if isinstance(name, str) and name:
            available.add(name.lower())
    return available


def unavailable_tool_usage(
    declared: list[str] | None, available: set[str] | None
) -> list[str] | None:
    """Declared connectors not in ``available``. ``[]`` when nothing declared;
    ``None`` when availability is undeterminable; case-insensitive match."""
    if not declared:
        return []
    if available is None:
        return None
    avail_lower = {a.lower() for a in available}
    return [d for d in declared if d.lower() not in avail_lower]
