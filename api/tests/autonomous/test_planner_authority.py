"""Tests for planner.py retrieve_authority integration — WS-E PR1a (Task 6).

Coverage:
- retrieve_authority ∈ PLANNER_ALLOWLIST
- validate_action_args accepts/rejects retrieve_authority arg shapes
  (WS-D non-fatal-observation boundary: structural type-check only, no DB/gateway)
- collect_evidence emits kind="authority" EvidenceItem for a retrieve_authority
  ToolResult (reads data["authority"]["text"] and data["authority"]["external_ref"])
- build_planner_messages includes available source names/type/jurisdiction/coverage
  (P3 minimal per ADR 0016 — never auth keys or cost fields)
"""

from __future__ import annotations

import pytest

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.planner import (
    PLANNER_ALLOWLIST,
    build_planner_messages,
    collect_evidence,
    validate_action_args,
)
from app.research.registry import AvailableSource

# ---------------------------------------------------------------------------
# PLANNER_ALLOWLIST — retrieve_authority must be in the closed set (PR1a)
# ---------------------------------------------------------------------------


def test_retrieve_authority_in_planner_allowlist() -> None:
    """retrieve_authority must be in the closed planner allowlist (WS-E PR1a)."""
    assert ToolIntent.retrieve_authority in PLANNER_ALLOWLIST


# ---------------------------------------------------------------------------
# validate_action_args — retrieve_authority structural guard
#
# Type-check only; must NOT hit DB/gateway.  A ValueError here becomes a
# non-fatal failed observation in the WS-D loop (never a crash).
# ---------------------------------------------------------------------------

_VALID_AUTHORITY_ARGS: dict[str, object] = {
    "source": "govinfo",
    "op": "search_authority",
    "args": {"collection": "USCODE", "query": "x"},
}


def test_validate_authority_args_valid_passes() -> None:
    """Well-formed retrieve_authority args are accepted without raising."""
    validate_action_args(ToolIntent.retrieve_authority, dict(_VALID_AUTHORITY_ARGS))


def test_validate_authority_args_missing_op_raises() -> None:
    """Missing 'op' field raises ValueError (WS-D non-fatal boundary)."""
    with pytest.raises(ValueError):
        validate_action_args(
            ToolIntent.retrieve_authority,
            {"source": "govinfo"},  # op absent
        )


def test_validate_authority_args_missing_source_raises() -> None:
    """Missing 'source' field raises ValueError."""
    with pytest.raises(ValueError):
        validate_action_args(
            ToolIntent.retrieve_authority,
            {"op": "search_authority"},  # source absent
        )


def test_validate_authority_args_non_dict_args_raises() -> None:
    """A non-dict 'args' value raises ValueError."""
    with pytest.raises(ValueError):
        validate_action_args(
            ToolIntent.retrieve_authority,
            {"source": "govinfo", "op": "search_authority", "args": "not-a-dict"},
        )


def test_validate_authority_args_non_str_source_raises() -> None:
    """Non-str 'source' (e.g. int) raises ValueError."""
    with pytest.raises(ValueError):
        validate_action_args(
            ToolIntent.retrieve_authority,
            {"source": 123, "op": "search_authority", "args": {}},
        )


def test_validate_authority_args_non_str_op_raises() -> None:
    """Non-str 'op' (e.g. list) raises ValueError."""
    with pytest.raises(ValueError):
        validate_action_args(
            ToolIntent.retrieve_authority,
            {"source": "govinfo", "op": ["bad"], "args": {}},
        )


# ---------------------------------------------------------------------------
# collect_evidence — retrieve_authority branch
#
# Reads ToolResult.data["authority"]["text"] and ["external_ref"];
# yields EvidenceItem(kind="authority", ref=external_ref, content=text).
# ---------------------------------------------------------------------------


def test_collect_evidence_authority_yields_kind_authority() -> None:
    """collect_evidence for retrieve_authority emits a kind='authority' EvidenceItem."""
    result = ToolResult(
        data={
            "authority": {
                "text": "No person shall deprive any individual of liberty...",
                "external_ref": "USCODE-2023-title42",
                "label": "42 U.S.C.",
                "url": "https://api.govinfo.gov/packages/USCODE-2023-title42",
                "content_kind": "statute",
            }
        },
        outcome="success",
    )
    items = collect_evidence(ToolIntent.retrieve_authority, result, start_n=3)
    assert len(items) == 1
    item = items[0]
    assert item.n == 3
    assert item.kind == "authority"
    assert item.ref == "USCODE-2023-title42"  # external_ref
    assert "liberty" in item.content  # text


def test_collect_evidence_authority_empty_on_failure() -> None:
    """collect_evidence returns [] when outcome != 'success'."""
    result = ToolResult(data={"authority": {}}, outcome="error")
    items = collect_evidence(ToolIntent.retrieve_authority, result, start_n=1)
    assert items == []


# ---------------------------------------------------------------------------
# build_planner_messages — source-awareness (P3 minimal, ADR 0016)
#
# The prompt must include source name/type/jurisdiction/coverage so the
# planner can choose a source.  It must NEVER include auth keys or cost
# fields (egress_tier, api_key, etc.).
# ---------------------------------------------------------------------------


def _make_govinfo_source(*, enabled: bool = True) -> AvailableSource:
    return AvailableSource(
        name="govinfo-prod",
        type="govinfo",
        jurisdiction="us-federal",
        coverage="U.S. Code + Code of Federal Regulations",
        content_kinds=("statute", "regulation"),
        enabled=enabled,
        egress_tier=2,
    )


def test_build_planner_messages_includes_source_type_and_jurisdiction() -> None:
    """Available source type and jurisdiction appear in the planner prompt (P3 minimal)."""
    src = _make_govinfo_source()
    msgs = build_planner_messages(
        goal="Is this agreement enforceable?",
        observations=[],
        allowlist=PLANNER_ALLOWLIST,
        available_sources=[src],
    )
    body = msgs[0]["content"] + msgs[1]["content"]
    assert "govinfo" in body
    assert "us-federal" in body


def test_build_planner_messages_no_auth_or_cost_in_sources() -> None:
    """Auth keys and cost fields must NOT appear in the planner prompt (P3 / ADR 0016)."""
    src = _make_govinfo_source()
    msgs = build_planner_messages(
        goal="Is this clause enforceable?",
        observations=[],
        allowlist=PLANNER_ALLOWLIST,
        available_sources=[src],
    )
    body = msgs[0]["content"] + msgs[1]["content"]
    assert "egress_tier" not in body
    assert "api_key" not in body


def test_build_planner_messages_backward_compat_no_sources() -> None:
    """build_planner_messages still works when available_sources is omitted (backward compat)."""
    msgs = build_planner_messages(
        goal="Is this clause enforceable?",
        observations=[],
        allowlist=PLANNER_ALLOWLIST,
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
