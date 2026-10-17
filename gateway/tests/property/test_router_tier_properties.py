"""Tier-derivation property tests for the router — DE-230.

:func:`app.router.derive_routed_inference_tier` is the pure core of
tier annotation (PRD §3.13): every routed request's tier comes out of
this lookup chain. The properties pin the resolution *order* — pair
override → provider override → type default → provider ``tier:`` —
and that the result is always a valid tier regardless of which layer
answered. A regression here silently re-tiers requests, which then
feeds wrong values into tier-floor refusal and anonymization gating.
"""

from __future__ import annotations

from typing import get_args

from hypothesis import given, strategies as st

from app.config import InferenceTiersConfig, ProviderConfig, ProviderType
from app.router import derive_routed_inference_tier

PROVIDER_TYPES: tuple[str, ...] = get_args(ProviderType)

tier = st.integers(min_value=1, max_value=5)
maybe_tier = st.none() | tier
name = st.text(alphabet="abcdefghijklmnopqrstuvwxyz-", min_size=1, max_size=12)


@given(
    provider_name=name,
    provider_type=st.sampled_from(PROVIDER_TYPES),
    native_model=name,
    provider_tier=tier,
    pair_override=maybe_tier,
    provider_override=maybe_tier,
    type_default=maybe_tier,
)
def test_tier_lookup_precedence_and_validity(
    provider_name: str,
    provider_type: str,
    native_model: str,
    provider_tier: int,
    pair_override: int | None,
    provider_override: int | None,
    type_default: int | None,
) -> None:
    """First matching layer wins; result is always the tier that layer holds."""

    provider = ProviderConfig(
        name=provider_name,
        type=provider_type,  # type: ignore[arg-type]
        base_url="http://provider.internal",
        tier=provider_tier,
        models=[native_model],
    )
    overrides: dict[str, int] = {}
    if pair_override is not None:
        overrides[f"{provider_name}/{native_model}"] = pair_override
    if provider_override is not None:
        overrides[provider_name] = provider_override
    defaults: dict[str, int] = {}
    if type_default is not None:
        defaults[provider_type] = type_default
    tiers = InferenceTiersConfig(overrides=overrides, defaults=defaults)  # type: ignore[arg-type]

    derived = derive_routed_inference_tier(
        provider=provider, native_model=native_model, inference_tiers=tiers
    )

    expected = next(
        value
        for value in (pair_override, provider_override, type_default, provider_tier)
        if value is not None
    )
    assert derived == expected
    assert 1 <= derived <= 5
