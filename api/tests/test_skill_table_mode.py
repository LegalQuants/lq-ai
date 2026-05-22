"""Unit tests for M3-C1 — ``output_format: table`` Skill mode.

Covers the new ``ColumnSpec`` model + the ``columns`` field on
``LQAIFrontmatter`` + the resolved-summary plumbing.

The loader-side WARNING when ``output_format == 'table'`` but
``columns`` is missing is covered in ``test_skills.py`` (loader
integration); this file owns the pure schema layer.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# ColumnSpec — the per-column definition
# ---------------------------------------------------------------------------


class TestColumnSpec:
    def test_accepts_name_and_query_minimally(self) -> None:
        """Minimal happy path: a column needs a ``name`` and a ``query``."""

        from app.skills.schema import ColumnSpec

        col = ColumnSpec(name="Term Length", query="What is the term length of this NDA?")

        assert col.name == "Term Length"
        assert col.query == "What is the term length of this NDA?"
        assert col.ensemble_verification is None
        assert col.minimum_inference_tier is None

    def test_accepts_per_column_overrides(self) -> None:
        """Per-column ``ensemble_verification`` + ``minimum_inference_tier``
        override the skill-level fields when present."""

        from app.skills.schema import ColumnSpec

        col = ColumnSpec(
            name="Indemnification",
            query="Summarize the indemnification clause.",
            ensemble_verification=True,
            minimum_inference_tier=4,
        )

        assert col.ensemble_verification is True
        assert col.minimum_inference_tier == 4

    def test_rejects_missing_name(self) -> None:
        """``name`` is required — the grid header has to come from somewhere."""

        from pydantic import ValidationError

        from app.skills.schema import ColumnSpec

        with pytest.raises(ValidationError):
            ColumnSpec(query="Some query")  # type: ignore[call-arg]

    def test_rejects_missing_query(self) -> None:
        """``query`` is required — the per-row prompt has to be specified."""

        from pydantic import ValidationError

        from app.skills.schema import ColumnSpec

        with pytest.raises(ValidationError):
            ColumnSpec(name="Some Column")  # type: ignore[call-arg]

    def test_rejects_inference_tier_out_of_range(self) -> None:
        """``minimum_inference_tier`` mirrors the skill-level constraint:
        1 ≤ tier ≤ 5."""

        from pydantic import ValidationError

        from app.skills.schema import ColumnSpec

        with pytest.raises(ValidationError):
            ColumnSpec(name="X", query="Y", minimum_inference_tier=0)

        with pytest.raises(ValidationError):
            ColumnSpec(name="X", query="Y", minimum_inference_tier=6)


# ---------------------------------------------------------------------------
# LQAIFrontmatter — the lq_ai: block gains a columns field
# ---------------------------------------------------------------------------


class TestLQAIFrontmatterColumns:
    def test_columns_defaults_to_none(self) -> None:
        """Absent ``columns`` field is None (existing report-mode skills
        unaffected)."""

        from app.skills.schema import LQAIFrontmatter

        fm = LQAIFrontmatter()

        assert fm.columns is None

    def test_columns_parses_list_of_specs(self) -> None:
        """``columns`` accepts a list of ColumnSpec-shaped dicts."""

        from app.skills.schema import LQAIFrontmatter

        fm = LQAIFrontmatter(
            output_format="table",
            columns=[
                {"name": "Term", "query": "What is the term?"},
                {"name": "Survival", "query": "What is the survival period?"},
            ],
        )

        assert fm.output_format == "table"
        assert fm.columns is not None
        assert len(fm.columns) == 2
        assert fm.columns[0].name == "Term"
        assert fm.columns[1].name == "Survival"

    def test_report_mode_can_carry_columns_field_without_effect(self) -> None:
        """A skill author iterating between modes can pre-write ``columns``
        on a report skill; the field is accepted but unused at parse time."""

        from app.skills.schema import LQAIFrontmatter

        fm = LQAIFrontmatter(
            output_format="report",
            columns=[{"name": "X", "query": "Y"}],
        )

        assert fm.output_format == "report"
        assert fm.columns is not None  # Parsed but downstream ignores it.


# ---------------------------------------------------------------------------
# SkillFrontmatter — end-to-end frontmatter parse of a table-mode skill
# ---------------------------------------------------------------------------


class TestSkillFrontmatterTableMode:
    def test_full_table_skill_parses(self) -> None:
        """Realistic table-mode skill frontmatter parses cleanly."""

        from app.skills.schema import SkillFrontmatter

        raw = {
            "name": "contract-snapshot",
            "description": "Extract a snapshot of key terms across N contracts.",
            "lq_ai": {
                "title": "Contract Snapshot",
                "version": "1.0.0",
                "output_format": "table",
                "tags": ["table", "due-diligence"],
                "columns": [
                    {"name": "Term", "query": "What is the term length?"},
                    {
                        "name": "Survival",
                        "query": "What survives termination?",
                        "ensemble_verification": True,
                        "minimum_inference_tier": 4,
                    },
                ],
            },
        }

        fm = SkillFrontmatter.model_validate(raw)

        assert fm.name == "contract-snapshot"
        assert fm.lq_ai.output_format == "table"
        assert fm.lq_ai.columns is not None
        assert len(fm.lq_ai.columns) == 2
        assert fm.lq_ai.columns[1].ensemble_verification is True
        assert fm.lq_ai.columns[1].minimum_inference_tier == 4


# ---------------------------------------------------------------------------
# Cross-field validation — table mode requires non-empty columns
# ---------------------------------------------------------------------------


class TestTableModeRequiresColumns:
    """``output_format: table`` without ``columns`` is a malformed skill.

    The loader catches the ValidationError and turns it into a
    LoaderError → WARNING → skip (same path as any other malformed
    frontmatter). Reflects Decision C-1: table-mode-without-columns
    cannot produce a grid, so the skill is rejected at load time
    rather than silently failing at execution.
    """

    def test_table_mode_without_columns_raises(self) -> None:
        from pydantic import ValidationError

        from app.skills.schema import LQAIFrontmatter

        with pytest.raises(ValidationError):
            LQAIFrontmatter(output_format="table")

    def test_table_mode_with_empty_columns_raises(self) -> None:
        from pydantic import ValidationError

        from app.skills.schema import LQAIFrontmatter

        with pytest.raises(ValidationError):
            LQAIFrontmatter(output_format="table", columns=[])

    def test_non_table_mode_without_columns_is_fine(self) -> None:
        """The 'every existing skill keeps working' assertion — no existing
        skill has ``columns`` set, and switching the validator on must
        not break them."""

        from app.skills.schema import LQAIFrontmatter

        # Original corpus shape — no output_format, no columns.
        LQAIFrontmatter()

        # Common corpus shapes — non-table output_format, no columns.
        LQAIFrontmatter(output_format="report")
        LQAIFrontmatter(output_format="markdown")
        LQAIFrontmatter(output_format="redline")
        LQAIFrontmatter(output_format="structured_checklist")


# ---------------------------------------------------------------------------
# derive_summary — columns shouldn't leak into the summary surface
# ---------------------------------------------------------------------------


class TestDeriveSummaryTableMode:
    def test_summary_carries_output_format_table(self) -> None:
        """The SkillSummary (list-endpoint shape) surfaces ``output_format``
        so the UI can render a 'table' badge, but columns themselves only
        appear on the Skill detail."""

        from app.skills.schema import SkillFrontmatter, derive_summary

        fm = SkillFrontmatter.model_validate(
            {
                "name": "contract-snapshot",
                "description": "Snapshot of key terms.",
                "lq_ai": {
                    "output_format": "table",
                    "columns": [{"name": "Term", "query": "What is the term?"}],
                },
            }
        )

        summary = derive_summary("contract-snapshot", fm)

        assert summary.output_format == "table"
        # SkillSummary intentionally does NOT include columns — columns are
        # a detail-page concern.
        assert not hasattr(summary, "columns")
