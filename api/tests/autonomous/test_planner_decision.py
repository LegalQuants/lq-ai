import json

import pytest

from app.autonomous.enums import ToolIntent
from app.autonomous.planner import (
    PLANNER_ALLOWLIST,
    PlannerDecision,
    build_planner_messages,
    parse_planner_decision,
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
