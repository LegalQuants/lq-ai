"""Tests for the Stage 3 paraphrase-judge prompt construction (M2-C1).

The Stage 3 judge is an LLM call made through the gateway with a
deterministic prompt: a system message that sets up the verification
task and a user message carrying the candidate claim and the source
context. The prompt's calibration (bias toward 'no'/'partial' on
uncertainty) is load-bearing — it controls the false-positive rate
that the M2-F1 acceptance corpus will measure.

These tests pin the prompt's *invariants* — the exact wording is
operator-tunable, but the structure (role split, JSON-only output
instruction, conservative bias, claim and source both present) must
hold.
"""

from __future__ import annotations

import pytest

from app.citation.judge_prompts import build_judge_prompt
from app.schemas.gateway import ChatCompletionMessage


@pytest.mark.unit
def test_build_judge_prompt_returns_system_and_user_messages() -> None:
    """The judge prompt is a two-message list: system then user."""

    messages = build_judge_prompt(claim_text="hello", chunks=["world"])

    assert len(messages) == 2
    assert all(isinstance(m, ChatCompletionMessage) for m in messages)
    assert messages[0].role == "system"
    assert messages[1].role == "user"


@pytest.mark.unit
def test_build_judge_prompt_system_message_specifies_json_shape() -> None:
    """System message tells the model the exact JSON output shape."""

    messages = build_judge_prompt(claim_text="hello", chunks=["world"])
    system_content = messages[0].content or ""

    # Verdict + confidence + justification — the three keys the
    # verify_paraphrase parser reads. Names must match.
    assert "verdict" in system_content
    assert "confidence" in system_content
    assert "justification" in system_content
    # Verdict and confidence enums.
    assert '"yes"' in system_content
    assert '"partial"' in system_content
    assert '"no"' in system_content
    assert '"high"' in system_content
    assert '"medium"' in system_content
    assert '"low"' in system_content


@pytest.mark.unit
def test_build_judge_prompt_system_message_has_conservative_bias() -> None:
    """The prompt explicitly biases toward 'no' / 'partial' on uncertainty.

    Calibration intent from M2-C1: false positives (calling an
    unsupported claim verified) are more harmful than false negatives
    in a legal-citation context. The prompt has to make this trade-off
    explicit or the model defaults to charitable interpretation.
    """

    messages = build_judge_prompt(claim_text="hello", chunks=["world"])
    system_content = (messages[0].content or "").lower()

    # The wording is operator-tunable; the substance must hold —
    # an explicit nudge toward "no" or "partial" when uncertain.
    assert "uncertain" in system_content or "unsure" in system_content
    assert "no" in system_content
    assert "partial" in system_content


@pytest.mark.unit
def test_build_judge_prompt_user_message_contains_claim() -> None:
    """The user message includes the model's quoted claim verbatim."""

    claim = "The plaintiff prevailed on the breach claim."
    messages = build_judge_prompt(claim_text=claim, chunks=["irrelevant"])
    user_content = messages[1].content or ""

    assert claim in user_content


@pytest.mark.unit
def test_build_judge_prompt_user_message_contains_all_chunks() -> None:
    """Every chunk gets embedded in the user message."""

    chunks = [
        "Section 5.1 of the agreement defines breach.",
        "Section 5.2 provides remedies for breach.",
        "Section 5.3 is the integration clause.",
    ]
    messages = build_judge_prompt(claim_text="claim", chunks=chunks)
    user_content = messages[1].content or ""

    for chunk in chunks:
        assert chunk in user_content


@pytest.mark.unit
def test_build_judge_prompt_user_message_labels_source_and_claim() -> None:
    """User message labels the source vs. claim distinctly so the model parses correctly.

    Without distinct labels (e.g. "SOURCE:" / "CLAIM:") the model can
    conflate the claim into the source text and produce noisy
    verdicts. The label format is internal but the existence is
    load-bearing.
    """

    messages = build_judge_prompt(claim_text="claim", chunks=["source"])
    user_content = (messages[1].content or "").lower()

    assert "source" in user_content
    assert "claim" in user_content


@pytest.mark.unit
def test_build_judge_prompt_handles_empty_chunks_list() -> None:
    """Empty ``chunks`` is degenerate but must not crash.

    The judge will likely return 'no' / 'low' confidence in this case
    (no source to support the claim) but the prompt construction
    itself stays well-formed.
    """

    messages = build_judge_prompt(claim_text="claim", chunks=[])

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    user_content = messages[1].content or ""
    assert "claim" in user_content
