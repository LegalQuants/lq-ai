"""Keyless structural tests for the skill acceptance corpus (DE-231).

These run everywhere — no stack, no provider key — and gate the shape of
``skills/<skill>/acceptance/``: every starter skill has >= 3 paired
fixtures/snapshots, every file parses against the documented format, and
the extraction heuristics used by the live harness behave on a known
sample. They are the "collects and passes keyless" half of DE-231's
acceptance criteria; the live half lives in test_skill_goldens.py.
"""

from __future__ import annotations

import pytest

from .golden_lib import (
    GOLDEN_SKILLS,
    MIN_FIXTURES_PER_SKILL,
    count_blockquote_lines,
    count_citations,
    count_regex,
    count_section_items,
    count_table_rows,
    discover_pairs,
    evaluate,
    find_section,
    load_fixture,
    load_snapshot,
)

PAIRS = discover_pairs()
PAIR_IDS = [f"{p.skill}--{p.fixture_id}" for p in PAIRS]


# ---------------------------------------------------------------------------
# Corpus inventory
# ---------------------------------------------------------------------------


class TestInventory:
    def test_every_starter_skill_has_an_acceptance_corpus(self) -> None:
        """Exactly the 10 starter skills carry acceptance corpora.

        Pinned set, same convention as api/tests' EXPECTED_PATHS: adding
        an acceptance/ dir to a new skill must update GOLDEN_SKILLS
        deliberately (and DE-231's docs with it).
        """

        covered = {p.skill for p in PAIRS}
        assert covered == set(GOLDEN_SKILLS), (
            f"acceptance corpora present for {sorted(covered)}, "
            f"expected exactly {sorted(GOLDEN_SKILLS)}"
        )

    def test_every_skill_has_at_least_three_fixtures(self) -> None:
        by_skill: dict[str, int] = {}
        for pair in PAIRS:
            by_skill[pair.skill] = by_skill.get(pair.skill, 0) + 1
        short = {s: n for s, n in by_skill.items() if n < MIN_FIXTURES_PER_SKILL}
        assert not short, f"skills below {MIN_FIXTURES_PER_SKILL} fixtures: {short}"


# ---------------------------------------------------------------------------
# Per-pair format checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
class TestPairFormat:
    def test_fixture_parses_and_is_coherent(self, pair) -> None:
        fixture = load_fixture(pair.fixture_path)
        assert fixture.skill == pair.skill, (
            f"{pair.fixture_path}: frontmatter skill {fixture.skill!r} "
            f"!= folder skill {pair.skill!r}"
        )
        assert fixture.fixture_id == pair.fixture_id, (
            f"{pair.fixture_path}: frontmatter fixture id {fixture.fixture_id!r} "
            f"!= file stem {pair.fixture_id!r}"
        )
        # The synthetic notice is the anonymization contract: fixtures are
        # authored test data, never real documents (DE-231 legal caution).
        assert "synthetic" in fixture.synthetic_notice.lower()
        # Document-review skills carry full synthetic instruments; prompt
        # skills (enhance-prompt) legitimately carry a short raw prompt.
        assert len(fixture.document.strip()) >= 30, (
            f"{pair.fixture_path}: document body suspiciously short — "
            "fixtures must carry realistic input material"
        )

    def test_snapshot_parses_and_is_coherent(self, pair) -> None:
        snapshot = load_snapshot(pair.snapshot_path)
        assert snapshot.skill == pair.skill
        assert snapshot.fixture_id == pair.fixture_id
        # Until a maintainer calibrates against a live run, ranges derive
        # from documented contracts only and must say so.
        if snapshot.status == "provisional":
            assert "not observed" in snapshot.provenance.lower(), (
                f"{pair.snapshot_path}: provisional snapshots must state their "
                "ranges are documented-contract-derived, not observed"
            )
        assert snapshot.required_sections or snapshot.metrics, (
            f"{pair.snapshot_path}: snapshot asserts nothing"
        )

    def test_snapshot_matches_a_loadable_fixture(self, pair) -> None:
        """A snapshot's assertions must be evaluable (smoke: empty doc)."""

        snapshot = load_snapshot(pair.snapshot_path)
        result = evaluate(snapshot, "")
        # An empty output must never satisfy a golden snapshot — if it
        # does, the snapshot cannot catch a degenerate/refusal response.
        assert not result.passed, (
            f"{pair.snapshot_path}: an empty response passes this snapshot — "
            "add min_chars / required_sections / a nonzero-min metric"
        )


# ---------------------------------------------------------------------------
# Extraction heuristics (unit tests for golden_lib)
# ---------------------------------------------------------------------------

_SAMPLE = """\
# NDA Review: Meridian Holdings LLC

**Perspective:** recipient

## Bottom line

Signable with edits. See below.

## Critical issues

### §7 Non-compete — overbroad restraint

The clause at Section 7.1 restricts competition.

### §9 IP assignment of feedback

Feedback assignment per Clause 9 is unusual.

## Material issues

- §3 definition of Confidential Information is unbounded
- Section 5 return obligations lack a certification carve-out

## Minor issues and observations

- Governing law (Article 12) is Delaware; venue is exclusive.

## Recommended next steps

- Negotiate §7 and §9 before signature.

| # | Required term | Status |
| --- | --- | --- |
| 1 | Definition | Present |
| 2 | Term | Partial |

> "Receiving Party shall not disclose..." (Section 2.1)
"""


class TestExtractionHeuristics:
    def test_find_section_is_case_insensitive_prefix(self) -> None:
        assert find_section(_SAMPLE, "bottom line") is not None
        assert find_section(_SAMPLE, "NDA Review") is not None  # dynamic suffix
        assert find_section(_SAMPLE, "Missing standard protections") is None

    def test_section_items_prefers_child_headings(self) -> None:
        assert count_section_items(_SAMPLE, "Critical issues") == 2

    def test_section_items_falls_back_to_bullets(self) -> None:
        assert count_section_items(_SAMPLE, "Material issues") == 2
        assert count_section_items(_SAMPLE, "Minor issues and observations") == 1

    def test_section_items_missing_section_counts_zero(self) -> None:
        assert count_section_items(_SAMPLE, "Operational red flags") == 0

    def test_citation_heuristic_counts_clause_references(self) -> None:
        # §7, §9, Section 7.1, Clause 9, §3, Section 5, Article 12,
        # §7 + §9 (next steps), Section 2.1 — at least these.
        assert count_citations(_SAMPLE) >= 9

    def test_blockquote_and_table_rows(self) -> None:
        assert count_blockquote_lines(_SAMPLE) == 1
        assert count_table_rows(_SAMPLE) == 2

    def test_regex_count_is_case_insensitive(self) -> None:
        assert count_regex(_SAMPLE, r"\bsignable\b") == 1
