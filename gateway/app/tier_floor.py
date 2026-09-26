"""Tier-floor resolution + refusal helpers (D1).

Per PRD §4.4, every chat-completion request can declare a *minimum
inference tier* — a security floor the gateway must enforce.  Three
independent declarations contribute:

1. **Request override** — ``ChatCompletionRequest.minimum_inference_tier``.
   Per-call clamping. Highest specificity (one request).
2. **Project** — forwarded by the backend on
   ``ChatCompletionRequest.lq_ai_project_minimum_inference_tier`` when the
   chat lives in a project. The backend is authoritative on chat ↔
   project; the gateway only sees the value forwarded on the request.
3. **Skill** — ``Skill.minimum_inference_tier`` (frontmatter field per
   the skill-authoring guide). Each attached skill contributes its own
   floor; multiple attached skills mean ``min(floors)`` (the strictest
   declared skill floor wins).

**PRD §1.5.2 tier ordering: lower number = stronger security.**
Tier 1 (local Ollama, air-gap-capable) is the most secure posture.
Tier 5 (consumer / free tier) is the least secure. A
``minimum_inference_tier`` value of N means "require Tier N security or
stronger" — i.e., the routed tier must be **≤ N** (a lower-numbered or
equal tier is equally or more secure; a higher-numbered tier is weaker).

The **effective floor** is ``min(any of the three)`` — the declaration
requiring the strongest (lowest-numbered) tier wins. ``None`` from any
source means "no opinion"; we ignore it. If every source is ``None``, no
floor applies and the request is never refused on this axis.

Worked example: a project marked ``privileged: true`` defaults to
``minimum_inference_tier: 2``. The gateway allows Tier 1 (stronger) and
Tier 2 (the floor), and refuses Tier 3-5 (weaker than the floor).

When the resolved routed tier is weaker than the effective floor (i.e.,
``resolved_tier > floor.value``), the gateway responds **HTTP 403** with
the structured ``tier_below_minimum`` error envelope and writes a
routing-log row carrying ``refused=True`` and
``refusal_reason='tier_below_minimum'``. Per PRD §4.4 / D1
verification cases (a)-(d).

This module is pure logic — no FastAPI / no DB / no Pydantic. The route
handler in :mod:`app.api.inference` calls :func:`resolve_tier_floor`
after skill-prompt assembly (so skill floors are visible) and before
dispatch (so refusal happens before any upstream call).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.clients.backend import Skill
from app.providers import ChatCompletionRequest


@dataclass(frozen=True)
class TierFloor:
    """Resolved tier floor with provenance.

    Under PRD §1.5.2, a lower tier number means stronger security.
    A floor of ``value=2`` allows Tier 1 (stronger than the floor) and
    Tier 2 (the floor itself) and refuses Tier 3-5 (weaker than the
    floor).  The gateway refuses a request when
    ``resolved_tier > floor.value`` — i.e., the routed tier is weaker
    (higher-numbered) than the declared floor.

    The provenance string is wired into the 403 response's
    ``details.source`` field so a caller looking at a refused request
    sees which declaration was binding (skill name / "project" /
    "request"). Operators reading audit logs see the same string in the
    ``refusal_reason`` row.
    """

    value: int
    """The effective floor value (most restrictive = lowest integer
    across all sources).  Under PRD §1.5.2, lower = stricter."""

    source: str
    """Human-readable origin: ``"request"``, ``"project"``, or
    ``"skill:<name>"``. When several sources tie at the same value, the
    request override wins, then project, then skill (in attachment
    order). Tie-breaking is purely diagnostic — the *value* is the same
    either way; we just want the surface to be deterministic so tests
    aren't flaky."""


def resolve_tier_floor(
    *,
    request: ChatCompletionRequest,
    skills: list[Skill] | None = None,
) -> TierFloor | None:
    """Compute the effective tier floor for a chat-completion request.

    Returns ``None`` when no source declared a floor — the request is
    not subject to D1 refusal on this axis.

    Under PRD §1.5.2 (lower tier number = stronger security), the most
    restrictive floor across all sources is the **lowest** integer value.
    The combiner is therefore ``min(values)`` — the declaration requiring
    the strongest (lowest-numbered) tier wins.

    Tie-breaking is deterministic per :class:`TierFloor.source`'s
    docstring: request > project > skill (attachment order). The
    *value* is identical across ties; we pick a stable source string so
    tests can pin a deterministic ``details.source``.
    """

    # Collect (value, priority, label) entries; priority is the
    # tie-break order (smaller wins on ties). The actual floor is
    # ``min(value)`` — the lowest tier number (= strongest security
    # posture) declared by any source wins.
    entries: list[tuple[int, int, str]] = []

    if request.minimum_inference_tier is not None:
        entries.append((int(request.minimum_inference_tier), 0, "request"))

    if request.lq_ai_project_minimum_inference_tier is not None:
        entries.append((int(request.lq_ai_project_minimum_inference_tier), 1, "project"))

    for index, skill in enumerate(skills or []):
        if skill.minimum_inference_tier is not None:
            entries.append((int(skill.minimum_inference_tier), 2 + index, f"skill:{skill.name}"))

    if not entries:
        return None

    min_value = min(e[0] for e in entries)
    # Among entries tied at the min, pick the one with the lowest
    # priority number. Stable sort means equal-priority entries stay in
    # insertion order — only relevant for skills (which already have
    # distinct priorities encoded by attachment index).
    candidates = [e for e in entries if e[0] == min_value]
    candidates.sort(key=lambda e: e[1])
    chosen = candidates[0]
    return TierFloor(value=chosen[0], source=chosen[2])


def apply_policy_floor(
    floor: TierFloor | None,
    *,
    default_minimum_tier: int,
    privileged_minimum_tier: int,
    privileged: bool,
) -> TierFloor:
    """Fold the operator ``tier_policy`` baseline into the resolved floor.

    Per PRD §4.4 / ``gateway.yaml.example``, the deployment declares a baseline
    minimum tier that applies even when the request / project / skill declared
    none (or a weaker one): ``privileged_minimum_tier`` for a privileged request,
    ``default_minimum_tier`` otherwise. The effective floor is the *stricter*
    (lower-numbered, per PRD §1.5.2) of the resolved floor and the policy floor.

    When the resolved floor is equal or stricter it is returned unchanged so its
    provenance (``request`` / ``project`` / ``skill:<name>``) is preserved for
    the refusal envelope; otherwise the policy floor wins.
    """

    policy_value = privileged_minimum_tier if privileged else default_minimum_tier
    policy_source = "tier_policy:privileged" if privileged else "tier_policy:default"
    if floor is not None and floor.value <= policy_value:
        return floor
    return TierFloor(value=policy_value, source=policy_source)


def is_refused(*, resolved_tier: int, floor: TierFloor | None) -> bool:
    """Return True iff the resolved tier is weaker than (strictly above) the floor.

    Under PRD §1.5.2 (lower tier number = stronger security), a request
    is refused when ``resolved_tier > floor.value`` — the routed model's
    tier is weaker (higher-numbered) than the declared floor.

    A floor of ``None`` (no declaration) never refuses. A resolved tier
    equal to the floor passes — the floor is the weakest tier that is
    still acceptable, not an exclusive bound.

    Example: floor=2 (requires Tier 2 or stronger).
    - resolved=1 → allowed  (Tier 1 is stronger than Tier 2)
    - resolved=2 → allowed  (Tier 2 equals the floor)
    - resolved=3 → refused  (Tier 3 is weaker than Tier 2)
    """

    if floor is None:
        return False
    return int(resolved_tier) > int(floor.value)


__all__ = ["TierFloor", "apply_policy_floor", "is_refused", "resolve_tier_floor"]
