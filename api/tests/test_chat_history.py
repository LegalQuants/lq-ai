"""Unit tests for multi-turn chat-history assembly in the send_message path.

Covers the pure budgeting/truncation helpers added to give chat real
multi-turn memory (replaying prior turns to the model). The DB-backed
loader (`_load_history_messages`) is exercised by the chats integration
suite against Postgres; these tests pin the trimming logic, which is the
part with the interesting edge cases.
"""

from __future__ import annotations

from app.api.chats import _estimate_tokens, _select_history_within_budget


def test_estimate_tokens_rough_four_chars_per_token() -> None:
    assert _estimate_tokens("") == 1  # never zero — avoids div-by-zero-ish edges
    assert _estimate_tokens("a") == 1
    assert _estimate_tokens("a" * 4) == 1
    assert _estimate_tokens("a" * 8) == 2


def test_select_history_empty() -> None:
    assert _select_history_within_budget([], token_budget=100, max_messages=10) == []


def test_select_history_returns_chronological_within_message_cap() -> None:
    hist = [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
        ("assistant", "a2"),
    ]
    out = _select_history_within_budget(hist, token_budget=10_000, max_messages=2)
    # most-recent two turns, restored to chronological order
    assert out == [("user", "u2"), ("assistant", "a2")]


def test_select_history_drops_oldest_over_token_budget() -> None:
    # each 4-char content ~= 1 token; budget of 2 keeps the most recent two
    hist = [("user", "aaaa"), ("assistant", "bbbb"), ("user", "cccc")]
    out = _select_history_within_budget(hist, token_budget=2, max_messages=100)
    assert out == [("assistant", "bbbb"), ("user", "cccc")]


def test_select_history_keeps_most_recent_even_if_over_budget() -> None:
    # the single most-recent turn is always kept, even if it alone busts the
    # budget — dropping it would discard the immediately-preceding context.
    hist = [("user", "short"), ("assistant", "x" * 400)]
    out = _select_history_within_budget(hist, token_budget=1, max_messages=100)
    assert out == [("assistant", "x" * 400)]


def test_select_history_disabled_by_zero_budget_or_zero_cap() -> None:
    hist = [("user", "u1"), ("assistant", "a1")]
    assert _select_history_within_budget(hist, token_budget=0, max_messages=10) == []
    assert _select_history_within_budget(hist, token_budget=10, max_messages=0) == []
