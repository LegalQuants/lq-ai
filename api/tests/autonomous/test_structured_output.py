"""Tests for the tolerant structured-output parser (M4 real-work Task 8).

The parser MUST NEVER raise on malformed input — every code path returns
a :class:`StructuredResult`, structured or unstructured. The drafting
node relies on this to decide between per-finding dispatch and a single
fallback finding with the raw content.
"""

from __future__ import annotations

import json

import pytest

from app.autonomous.structured_output import (
    StructuredResult,
    parse_structured_output,
)


def test_parse_well_formed_json() -> None:
    raw = """Here is my analysis.
```json
{
  "findings": [{"title": "F1", "summary": "S1", "severity": "info", "source_chunk_ids": []}],
  "suggested_memories": [{"category": "preference", "content": "C", "rationale": "R"}],
  "suggested_precedents": [{"pattern_kind": "clause", "summary": "P"}],
  "privilege_concerns": [],
  "scope_concerns": ["minor"]
}
```"""
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert len(r.findings) == 1
    assert r.findings[0]["title"] == "F1"
    assert len(r.suggested_memories) == 1
    assert len(r.suggested_precedents) == 1
    assert r.privilege_concerns == []
    assert r.scope_concerns == ["minor"]


def test_parse_json_without_fences() -> None:
    raw = (
        '{"findings": [], "suggested_memories": [], "suggested_precedents": [], '
        '"privilege_concerns": [], "scope_concerns": []}'
    )
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert r.findings == []


def test_parse_malformed_returns_unstructured_with_raw() -> None:
    raw = "I couldn't follow the format instructions, sorry."
    r = parse_structured_output(raw)
    assert r.is_structured is False
    assert r.raw_content == raw


def test_parse_empty_content_is_unstructured() -> None:
    r = parse_structured_output(None)
    assert r.is_structured is False
    assert r.raw_content == ""


def test_parse_partial_json_missing_arrays_defaults_to_empty() -> None:
    raw = (
        '```json\n{"findings": [{"title": "X", "summary": "Y", '
        '"severity": "warn", "source_chunk_ids": []}]}\n```'
    )
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert len(r.findings) == 1
    # Missing arrays default to []
    assert r.suggested_memories == []
    assert r.suggested_precedents == []
    assert r.privilege_concerns == []
    assert r.scope_concerns == []


def test_parse_top_level_list_is_unstructured() -> None:
    """Top-level non-dict JSON must be treated as unstructured."""
    r = parse_structured_output("[1, 2, 3]")
    assert r.is_structured is False
    assert r.raw_content == "[1, 2, 3]"


def test_parse_top_level_string_is_unstructured() -> None:
    """A bare JSON string is not a structured analysis result."""
    r = parse_structured_output('"hello"')
    assert r.is_structured is False
    assert r.raw_content == '"hello"'


def test_parse_empty_string_is_unstructured() -> None:
    r = parse_structured_output("")
    assert r.is_structured is False
    assert r.raw_content == ""


def test_unstructured_classmethod_handles_none() -> None:
    r = StructuredResult.unstructured(None)
    assert r.is_structured is False
    assert r.raw_content == ""


def test_parse_unlabeled_fence_is_accepted() -> None:
    """A plain ``` ``` fence (no `json` tag) is still recognised."""
    raw = '```\n{"findings": [], "suggested_memories": [], "suggested_precedents": [], "privilege_concerns": [], "scope_concerns": []}\n```'
    r = parse_structured_output(raw)
    assert r.is_structured is True


def test_parse_malformed_fenced_json_falls_back_to_whole_content() -> None:
    """A broken fence shouldn't shadow a valid whole-content JSON parse."""
    # Fence contains a half-broken object; the whole content (after
    # stripping fences) is not valid JSON either, so we expect a tolerant
    # unstructured return — i.e. no exception.
    raw = "```json\n{broken\n```"
    r = parse_structured_output(raw)
    assert r.is_structured is False
    assert r.raw_content == raw


def test_parse_non_array_value_for_array_key_defaults_to_empty() -> None:
    """Non-list values for array keys MUST coerce to [] — never raise.

    Pins the never-raise contract (see prompts.py:57-62 CONTRACT FOR TASK 8).
    """
    cases = [
        '{"findings": 42}',  # int → previously TypeError
        '{"findings": false}',  # bool → previously TypeError
        '{"findings": null}',  # null → already empty via current `or []`
        '{"findings": "text"}',  # string → previously silent corruption
        '{"findings": {"a": 1}}',  # dict → previously silent corruption
    ]
    for bad in cases:
        r = parse_structured_output(bad)
        assert r.is_structured is True, f"Case {bad!r} should still be structured"
        assert r.findings == [], f"Case {bad!r} should produce findings=[]"


def test_parse_artifacts_array() -> None:
    """The optional ``artifacts`` key (Donna ask #8) is parsed — and the
    parser is flag-agnostic: it fills the list regardless of the session's
    emit_artifacts opt-in (the drafting node enforces opt-in)."""
    raw = (
        '```json\n{"findings": [], '
        '"artifacts": [{"name": "review-memo.md", "content_md": "# Memo\\n\\nBody."}, '
        '{"name": "summary.md", "content_md": "# Summary"}]}\n```'
    )
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert len(r.artifacts) == 2
    assert r.artifacts[0]["name"] == "review-memo.md"
    assert r.artifacts[0]["content_md"] == "# Memo\n\nBody."


def test_parse_missing_artifacts_defaults_to_empty() -> None:
    """A response without the artifacts key (the common, non-opted-in
    case) yields artifacts == []."""
    raw = '{"findings": []}'
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert r.artifacts == []


def test_parse_non_list_artifacts_coerces_to_empty() -> None:
    """Non-list values for artifacts coerce to [] — never raise."""
    for bad in ('{"artifacts": 42}', '{"artifacts": "memo"}', '{"artifacts": {"a": 1}}'):
        r = parse_structured_output(bad)
        assert r.is_structured is True, f"Case {bad!r} should still be structured"
        assert r.artifacts == [], f"Case {bad!r} should produce artifacts=[]"


@pytest.mark.parametrize(
    "key",
    ["findings", "suggested_memories", "suggested_precedents", "artifacts"],
)
def test_parse_non_dict_items_in_dict_shaped_arrays_are_dropped(key: str) -> None:
    """Non-dict items inside dict-shaped arrays are silently dropped.

    Valid JSON like ``{"artifacts": ["a string"]}`` previously survived
    parsing and crashed the drafting node's ``.get()`` calls
    (AttributeError → run marked failed) — worse than the documented
    tolerant degradation. Only dict items may reach the drafting node.
    """
    survivor = {"title": "ok", "name": "a.md", "content_md": "x"}
    raw = json.dumps({key: ["a string", 42, None, True, [1, 2], survivor]})
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert getattr(r, key) == [survivor], f"key={key} should keep only dict items"


def test_parse_mixed_contamination_across_all_dict_shaped_arrays() -> None:
    """All four dict-shaped arrays drop non-dict items in one response;
    the string arrays (privilege/scope concerns) are untouched — they are
    only ever string-formatted downstream, never ``.get()``-accessed."""
    raw = json.dumps(
        {
            "findings": ["str", {"title": "ok"}],
            "suggested_memories": [1, {"category": "preference", "content": "C"}],
            "suggested_precedents": [None, {"pattern_kind": "clause"}],
            "artifacts": [42, {"name": "a.md", "content_md": "x"}],
            "privilege_concerns": ["p1"],
            "scope_concerns": ["s1"],
        }
    )
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert r.findings == [{"title": "ok"}]
    assert r.suggested_memories == [{"category": "preference", "content": "C"}]
    assert r.suggested_precedents == [{"pattern_kind": "clause"}]
    assert r.artifacts == [{"name": "a.md", "content_md": "x"}]
    assert r.privilege_concerns == ["p1"]
    assert r.scope_concerns == ["s1"]


def test_parse_non_array_value_does_not_raise_on_any_array_key() -> None:
    """Every array key in the schema must coerce non-list to []."""
    for key in (
        "findings",
        "suggested_memories",
        "suggested_precedents",
        "privilege_concerns",
        "scope_concerns",
        "artifacts",
    ):
        # Non-list value at the key under test:
        raw = '{"' + key + '": 99}'
        r = parse_structured_output(raw)
        assert r.is_structured is True
        # Read the coerced field via getattr to compare uniformly:
        assert getattr(r, key) == [], f"key={key} should coerce to []"
