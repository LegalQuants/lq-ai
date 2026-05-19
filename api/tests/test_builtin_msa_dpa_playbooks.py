"""Tests for the M3-A5 built-in playbooks (MSA-SaaS, DPA-GDPR, MSA-Commercial-Purchase).

Mirrors the structure of ``test_builtin_nda_playbooks.py`` (M3-A3):

* **YAML structural validation** — each ``skills/playbooks/*/playbook.yaml``
  loads, parses, and validates against the :class:`PlaybookCreate`
  Pydantic schema. Per-position structural invariants (≥2 fallback
  tiers, required string fields, canonical severity enum).
* **Disclaimer enforcement** — every playbook's ``description`` field
  contains the "not legal advice" + "professional judgment" framing
  per Decision F + the 2026-05-19 starting-point clarification.
* **Migration round-trip** — after migration 0033 runs, each playbook
  is present in ``playbooks`` + ``playbook_positions`` with content
  matching the YAML byte-for-byte.

The tests share the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.playbook import Playbook, PlaybookPosition
from app.schemas.playbooks import PlaybookCreate

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PLAYBOOKS_DIR = _REPO_ROOT / "skills" / "playbooks"

_BUILTIN_SLUGS: list[str] = ["msa-saas", "dpa-gdpr", "msa-commercial-purchase"]

_EXPECTED_NAMES: dict[str, str] = {
    "msa-saas": "MSA — SaaS (customer-perspective)",
    "dpa-gdpr": "DPA — GDPR (controller-to-processor)",
    "msa-commercial-purchase": "MSA — Commercial Services (purchase-side)",
}
_EXPECTED_CONTRACT_TYPES: dict[str, str] = {
    "msa-saas": "MSA-SaaS",
    "dpa-gdpr": "DPA-GDPR",
    "msa-commercial-purchase": "MSA-Commercial-Purchase",
}
_EXPECTED_POSITION_COUNTS: dict[str, int] = {
    "msa-saas": 11,
    "dpa-gdpr": 8,
    "msa-commercial-purchase": 10,
}


def _load_yaml(slug: str) -> dict[str, Any]:
    path = _PLAYBOOKS_DIR / slug / "playbook.yaml"
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# YAML structural validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_playbook_yaml_parses(slug: str) -> None:
    """The YAML file exists, parses, and is a dict."""
    parsed = _load_yaml(slug)
    assert isinstance(parsed, dict)


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_playbook_yaml_validates_against_pydantic_schema(slug: str) -> None:
    """The YAML conforms to :class:`PlaybookCreate` — same schema the
    executor and the M3-A4 UI consume.
    """
    parsed = _load_yaml(slug)
    pb = PlaybookCreate.model_validate(parsed)
    assert pb.name == _EXPECTED_NAMES[slug]
    assert pb.contract_type == _EXPECTED_CONTRACT_TYPES[slug]
    assert pb.version == "1.0.0"


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_playbook_has_expected_position_count(slug: str) -> None:
    """Position count matches the M3-A5 spec for each playbook."""
    parsed = _load_yaml(slug)
    positions = parsed.get("positions") or []
    expected = _EXPECTED_POSITION_COUNTS[slug]
    assert len(positions) == expected, (
        f"{slug}: expected {expected} positions, got {len(positions)}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_position_has_at_least_two_fallback_tiers(slug: str) -> None:
    """The M3-A5 spec inherits M3-A3's requirement of ≥2 fallback tiers per position."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        tiers = pos.get("fallback_tiers") or []
        assert len(tiers) >= 2, (
            f"{slug}/{pos['issue']}: only {len(tiers)} fallback tier(s); spec requires ≥2."
        )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_position_has_required_string_fields(slug: str) -> None:
    """Standard language, redline_strategy, severity, and detection_keywords are populated."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        assert pos.get("standard_language"), f"{slug}/{pos['issue']}: missing standard_language."
        assert pos.get("redline_strategy"), f"{slug}/{pos['issue']}: missing redline_strategy."
        assert pos.get("severity_if_missing") in {"critical", "high", "medium", "low"}, (
            f"{slug}/{pos['issue']}: severity_if_missing not in canonical enum."
        )
        assert pos.get("detection_keywords"), (
            f"{slug}/{pos['issue']}: detection_keywords must be non-empty."
        )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_fallback_tier_has_required_fields(slug: str) -> None:
    """Each fallback tier has rank, description, and language."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        for tier in pos.get("fallback_tiers") or []:
            assert isinstance(tier.get("rank"), int) and tier["rank"] >= 1, (
                f"{slug}/{pos['issue']}: fallback tier rank must be a positive int."
            )
            assert tier.get("description"), (
                f"{slug}/{pos['issue']}/rank={tier.get('rank')}: missing description."
            )
            assert tier.get("language"), (
                f"{slug}/{pos['issue']}/rank={tier.get('rank')}: missing language."
            )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_position_order_is_dense_and_zero_indexed(slug: str) -> None:
    """Position order values are 0, 1, 2, ..., N-1 with no gaps."""
    parsed = _load_yaml(slug)
    positions = parsed.get("positions") or []
    orders = sorted(int(p.get("position_order", 0)) for p in positions)
    expected = list(range(len(positions)))
    assert orders == expected, f"{slug}: position_order values {orders} are not dense 0..N-1."


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_description_includes_not_legal_advice_disclaimer(slug: str) -> None:
    """Every M3-A5 playbook's description carries the Decision F disclaimer.

    Per Decision F (M3-A3) + the 2026-05-19 starting-point clarification,
    every built-in playbook's ``description`` must surface the
    not-legal-advice posture and reference professional judgment so it
    renders wherever the playbook is shown (list page, execute modal,
    result view).
    """
    parsed = _load_yaml(slug)
    desc = (parsed.get("description") or "").lower()
    assert "not legal advice" in desc, (
        f"{slug}/playbook.yaml: description must include the 'not legal advice' disclaimer."
    )
    # The M3-A5 playbooks make the starting-point framing more explicit
    # than M3-A3 did. Accept either "professional judgment" (M3-A3 idiom)
    # or "starting point" (M3-A5 idiom) so the test is forward-compatible
    # if M3-A3 descriptions are retro-updated.
    assert "professional judgment" in desc or "starting point" in desc, (
        f"{slug}/playbook.yaml: description must reference professional judgment or starting-point posture."
    )


# ---------------------------------------------------------------------------
# Migration round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
async def test_migration_seeded_playbook_row(db_session: AsyncSession, slug: str) -> None:
    """After migration 0033 runs, the playbook row exists with the YAML content."""
    parsed = _load_yaml(slug)
    expected_name = _EXPECTED_NAMES[slug]

    result = await db_session.execute(
        select(Playbook).where(Playbook.name == expected_name, Playbook.version == "1.0.0")
    )
    pb = result.scalar_one()
    assert pb.contract_type == parsed["contract_type"]
    assert pb.description == parsed.get("description", "")


@pytest.mark.integration
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
async def test_migration_seeded_positions_match_yaml(db_session: AsyncSession, slug: str) -> None:
    """All positions are present after seeding with content matching the YAML."""
    parsed = _load_yaml(slug)
    expected_name = _EXPECTED_NAMES[slug]
    expected_count = _EXPECTED_POSITION_COUNTS[slug]

    pb_result = await db_session.execute(
        select(Playbook).where(Playbook.name == expected_name, Playbook.version == "1.0.0")
    )
    pb = pb_result.scalar_one()

    positions_result = await db_session.execute(
        select(PlaybookPosition)
        .where(PlaybookPosition.playbook_id == pb.id)
        .order_by(PlaybookPosition.position_order)
    )
    positions = list(positions_result.scalars().all())
    assert len(positions) == expected_count, (
        f"{slug}: expected {expected_count} positions, got {len(positions)}"
    )

    yaml_positions = sorted(
        (parsed.get("positions") or []), key=lambda p: int(p.get("position_order", 0))
    )
    for db_pos, yaml_pos in zip(positions, yaml_positions, strict=True):
        assert db_pos.issue == yaml_pos["issue"]
        assert db_pos.standard_language == yaml_pos["standard_language"]
        assert db_pos.redline_strategy == yaml_pos["redline_strategy"]
        assert db_pos.severity_if_missing == yaml_pos["severity_if_missing"]
        assert list(db_pos.detection_keywords) == list(yaml_pos.get("detection_keywords") or [])
        assert db_pos.fallback_tiers == (yaml_pos.get("fallback_tiers") or [])
