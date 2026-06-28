import json

import pytest

from app.autonomous.enums import ToolIntent
from app.autonomous.planner import (
    PLANNER_ALLOWLIST,
    PlannerDecision,
    build_planner_messages,
    parse_planner_decision,
    validate_action_args,
)


def test_allowlist_is_observe_intents_only():
    assert (
        frozenset(
            {ToolIntent.retrieve_chunks, ToolIntent.retrieve_caselaw, ToolIntent.call_mcp_tool}
        )
        == PLANNER_ALLOWLIST
    )


def test_prompt_carries_goal_observations_and_allowlist():
    msgs = build_planner_messages(
        goal="Is the assignment clause enforceable?",
        observations=["retrieve_caselaw → 2 results: [Smith (9th 2021); Doe (2d 2019)]"],
        allowlist=PLANNER_ALLOWLIST,
    )
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    body = msgs[0]["content"] + msgs[1]["content"]
    assert "assignment clause" in body
    assert "Smith (9th 2021)" in body
    for intent in PLANNER_ALLOWLIST:
        assert intent.value in body  # the allowlist is shown to the planner


def test_parse_action_decision():
    out = parse_planner_decision(
        json.dumps(
            {
                "next_intent": "retrieve_caselaw",
                "args": {"query": "assignment clause change of control"},
                "rationale": "Need controlling authority on assignment survival.",
            }
        )
    )
    assert out == PlannerDecision(
        done=False,
        next_intent=ToolIntent.retrieve_caselaw,
        args={"query": "assignment clause change of control"},
        rationale="Need controlling authority on assignment survival.",
    )


def test_parse_done_decision():
    out = parse_planner_decision(
        json.dumps({"done": True, "rationale": "Enough authority gathered."})
    )
    assert out is not None and out.done is True and out.next_intent is None


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "not json",
        json.dumps(
            {"next_intent": "emit_finding", "args": {}, "rationale": "x"}
        ),  # out of allowlist
        json.dumps(
            {"next_intent": "run_skill", "args": {}, "rationale": "x"}
        ),  # reserved for synthesis
        json.dumps(["retrieve_caselaw"]),  # not a dict
        json.dumps({"args": {}, "rationale": "x"}),  # no next_intent, no done
    ],
)
def test_parse_returns_none_on_garbage_or_out_of_set(bad):
    assert parse_planner_decision(bad) is None


# ---------------------------------------------------------------------------
# validate_action_args unit tests (C1 — WS-D PR1)
# ---------------------------------------------------------------------------


def test_validate_action_args_valid_top_k_passes():
    """A positive integer top_k is accepted."""
    validate_action_args(ToolIntent.retrieve_chunks, {"top_k": 5, "query": "x", "kb_id": "k"})


def test_validate_action_args_absent_top_k_passes():
    """Omitted top_k (None default) is accepted — the handler supplies its own default."""
    validate_action_args(ToolIntent.retrieve_chunks, {"query": "x", "kb_id": "k"})


@pytest.mark.parametrize(
    "bad_top_k",
    [-1, 0, True, "5"],
)
def test_validate_action_args_bad_top_k_raises(bad_top_k):
    """top_k=-1, 0, bool(True), or str('5') all raise ValueError."""
    with pytest.raises(ValueError, match="top_k"):
        validate_action_args(ToolIntent.retrieve_chunks, {"top_k": bad_top_k, "query": "x"})


def test_validate_action_args_valid_embedding_passes():
    """A list of floats is accepted."""
    validate_action_args(
        ToolIntent.retrieve_chunks,
        {"query_embedding": [0.1, 0.2, 0.3], "query": "x", "kb_id": "k"},
    )


def test_validate_action_args_none_embedding_passes():
    """Explicit None query_embedding is accepted (handler treats it as absent)."""
    validate_action_args(
        ToolIntent.retrieve_chunks,
        {"query_embedding": None, "query": "x", "kb_id": "k"},
    )


@pytest.mark.parametrize(
    "bad_emb",
    ["x", [("a",)]],
)
def test_validate_action_args_bad_embedding_raises(bad_emb):
    """A string or a list of tuples for query_embedding raises ValueError."""
    with pytest.raises(ValueError, match="query_embedding"):
        validate_action_args(ToolIntent.retrieve_chunks, {"query_embedding": bad_emb, "query": "x"})


def test_validate_action_args_non_retrieve_chunks_is_noop():
    """Non-retrieve_chunks intents pass unconditionally (no SQL reach)."""
    validate_action_args(ToolIntent.retrieve_caselaw, {"top_k": -999, "query_embedding": "bad"})
    validate_action_args(ToolIntent.call_mcp_tool, {"top_k": -1})
