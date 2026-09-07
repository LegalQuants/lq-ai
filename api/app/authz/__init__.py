"""Authorization policy — one place where "may this caller touch this?" is decided.

Today this package holds matter (project) access control. Before it existed,
the answer was a ``owner_id == user.id`` predicate copy-pasted into every
handler that touched a matter-scoped model; a single missed copy is a
privilege leak that no test names.

Per ADR 0016 P6 ("one governance path, not two"), the policy lives in one
module and every matter-scoped route goes through it — the human-side
analogue of the autonomous layer's single ``guarded_tool_call`` chokepoint.
"""

from app.authz.matters import (
    MatterAccess,
    matter_access,
    matter_access_map,
    matter_scope_filter,
    require_matter,
    resolve_access,
    visible_project_ids,
)

__all__ = [
    "MatterAccess",
    "matter_access",
    "matter_access_map",
    "matter_scope_filter",
    "require_matter",
    "resolve_access",
    "visible_project_ids",
]
