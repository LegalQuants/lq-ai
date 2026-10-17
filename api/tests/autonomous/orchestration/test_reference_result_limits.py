"""Receipt expansion never widens other tools or the admitted file profile."""

import pytest

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.store import _effect_result_json
from app.errors import ValidationError


@pytest.mark.parametrize(
    "data",
    [
        {"path": "references/guide.md", "content": "\x01" * 65537},
        {"path": "references/guide.md", "content": "\x00"},
        {"path": "../private.md", "content": "text"},
        {"path": "references/guide.md", "content": "text", "extra": "\x01" * 65536},
        {"path": "references/guide.md", "content": 1},
    ],
    ids=["over-file-limit", "nul", "outside-reference", "extra-data", "not-text"],
)
def test_reference_receipts_enforce_the_original_file_profile(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Effect result must be bounded JSON"):
        _effect_result_json({"data": data, "outcome": "success"}, ToolIntent.skill_reference_read)


def test_reference_receipt_cannot_carry_unbounded_extra_metadata() -> None:
    with pytest.raises(ValidationError, match="Effect result must be bounded JSON"):
        _effect_result_json(
            {
                "data": {"path": "references/guide.md", "content": "text"},
                "outcome": "success",
                "extra": "\x01" * 65536,
            },
            ToolIntent.skill_reference_read,
        )


@pytest.mark.parametrize("intent", [ToolIntent.run_skill, ToolIntent.skill_workspace_read])
def test_reference_shaped_data_cannot_select_a_larger_receipt_budget(intent: ToolIntent) -> None:
    with pytest.raises(ValidationError, match="Effect result must be bounded JSON"):
        _effect_result_json(
            {
                "data": {"path": "references/guide.md", "content": "\x01" * 65536},
                "outcome": "success",
            },
            intent,
        )


def test_failed_reference_results_keep_the_default_receipt_budget() -> None:
    with pytest.raises(ValidationError, match="Effect result must be bounded JSON"):
        _effect_result_json(
            {"data": {"error": "\x01" * 65536}, "outcome": "skill_tool_refused"},
            ToolIntent.skill_reference_read,
        )
