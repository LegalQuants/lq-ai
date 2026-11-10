"""Tier-floor enforcement property tests — DE-230.

Pins PRD §1.5.2 / §4.4 (D1) as algebra, over every combination of
request / project / skill floor declarations:

* the effective floor is the *minimum* declared value (lower tier
  number = stronger security; the strictest declaration wins);
* the gateway refuses **iff** the routed tier is weaker (numerically
  greater) than that minimum — so no request is ever served on a tier
  weaker than any declared floor, and no request is refused when every
  declared floor allows it;
* refusal is monotone: if tier ``t`` passes, every stronger tier
  passes too;
* provenance tie-breaking is deterministic (request > project > skill
  in attachment order).
"""

from __future__ import annotations

from hypothesis import given, strategies as st

from app.clients.backend import Skill
from app.providers import ChatCompletionMessage, ChatCompletionRequest
from app.tier_floor import is_refused, resolve_tier_floor

tier = st.integers(min_value=1, max_value=5)
maybe_tier = st.none() | tier
skill_floors = st.lists(maybe_tier, max_size=4)


def _build(
    request_floor: int | None,
    project_floor: int | None,
    floors: list[int | None],
) -> tuple[ChatCompletionRequest, list[Skill]]:
    request = ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content="hello")],
        minimum_inference_tier=request_floor,
        lq_ai_project_minimum_inference_tier=project_floor,
    )
    skills = [
        Skill(name=f"skill-{index}", minimum_inference_tier=floor)
        for index, floor in enumerate(floors)
    ]
    return request, skills


@given(request_floor=maybe_tier, project_floor=maybe_tier, floors=skill_floors)
def test_effective_floor_is_min_of_declared(
    request_floor: int | None, project_floor: int | None, floors: list[int | None]
) -> None:
    """resolve_tier_floor returns min(declared), or None when nothing declared."""

    request, skills = _build(request_floor, project_floor, floors)
    declared = [f for f in (request_floor, project_floor, *floors) if f is not None]
    floor = resolve_tier_floor(request=request, skills=skills)
    if not declared:
        assert floor is None
    else:
        assert floor is not None
        assert floor.value == min(declared)


@given(
    request_floor=maybe_tier,
    project_floor=maybe_tier,
    floors=skill_floors,
    resolved_tier=tier,
)
def test_refused_iff_routed_tier_weaker_than_every_declared_floor(
    request_floor: int | None,
    project_floor: int | None,
    floors: list[int | None],
    resolved_tier: int,
) -> None:
    """The fail-closed pin: a request is refused exactly when the routed
    tier is weaker (higher-numbered) than the strictest declared floor.

    Consequence in both directions: the gateway never *serves* a
    request on a tier weaker than a declared floor, and never *refuses*
    a request every declared floor allows.
    """

    request, skills = _build(request_floor, project_floor, floors)
    declared = [f for f in (request_floor, project_floor, *floors) if f is not None]
    floor = resolve_tier_floor(request=request, skills=skills)
    refused = is_refused(resolved_tier=resolved_tier, floor=floor)
    assert refused == (bool(declared) and resolved_tier > min(declared))


@given(request_floor=maybe_tier, project_floor=maybe_tier, floors=skill_floors, resolved_tier=tier)
def test_refusal_is_monotone_in_tier_strength(
    request_floor: int | None,
    project_floor: int | None,
    floors: list[int | None],
    resolved_tier: int,
) -> None:
    """If tier t is allowed, every stronger (lower-numbered) tier is allowed;
    if tier t is refused, every weaker (higher-numbered) tier is refused."""

    request, skills = _build(request_floor, project_floor, floors)
    floor = resolve_tier_floor(request=request, skills=skills)
    if not is_refused(resolved_tier=resolved_tier, floor=floor):
        for stronger in range(1, resolved_tier):
            assert not is_refused(resolved_tier=stronger, floor=floor)
    else:
        for weaker in range(resolved_tier, 6):
            assert is_refused(resolved_tier=weaker, floor=floor)


@given(request_floor=maybe_tier, project_floor=maybe_tier, floors=skill_floors)
def test_provenance_names_a_source_that_declared_the_min(
    request_floor: int | None, project_floor: int | None, floors: list[int | None]
) -> None:
    """floor.source is deterministic: request > project > first skill,
    among the sources tied at the minimum value."""

    request, skills = _build(request_floor, project_floor, floors)
    floor = resolve_tier_floor(request=request, skills=skills)
    if floor is None:
        return
    if request_floor == floor.value:
        assert floor.source == "request"
    elif project_floor == floor.value:
        assert floor.source == "project"
    else:
        first_declaring = next(index for index, value in enumerate(floors) if value == floor.value)
        assert floor.source == f"skill:skill-{first_declaring}"
