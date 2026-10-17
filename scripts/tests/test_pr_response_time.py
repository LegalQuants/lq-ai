"""Unit tests for scripts/pr_response_time.py (issue #699).

The GitHub calls are not exercised here; the tests feed GraphQL-shaped nodes
into ``parse_pr`` and ``classify`` and check the rules the script prints.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pr_response_time as prt

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=30)
MAINTAINERS = {"maint"}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def user(login: str, *, bot: bool = False) -> dict[str, str]:
    return {"__typename": "Bot" if bot else "User", "login": login}


def node(
    number: int,
    *,
    author: dict[str, str] | None = None,
    reviews: list[dict[str, Any]] | None = None,
    comments: list[dict[str, Any]] | None = None,
    merged_by: dict[str, str] | None = None,
    merged_at: datetime | None = None,
    closed_at: datetime | None = None,
    closed_by: dict[str, str] | None = None,
    draft: bool = False,
    created: datetime = T0,
    review_total: int | None = None,
    comment_total: int | None = None,
) -> dict[str, Any]:
    reviews = reviews or []
    comments = comments or []
    timeline = []
    if closed_at and closed_by:
        timeline.append({"createdAt": iso(closed_at), "actor": closed_by})
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://example.test/pull/{number}",
        "createdAt": iso(created),
        "isDraft": draft,
        "merged": merged_at is not None,
        "mergedAt": iso(merged_at) if merged_at else None,
        "closedAt": iso(closed_at or merged_at) if (closed_at or merged_at) else None,
        "author": author or user("contrib"),
        "mergedBy": merged_by,
        "reviews": {
            "totalCount": review_total if review_total is not None else len(reviews),
            "nodes": reviews,
        },
        "comments": {
            "totalCount": comment_total if comment_total is not None else len(comments),
            "nodes": comments,
        },
        "timelineItems": {"nodes": timeline},
    }


def review(who: dict[str, str], at: datetime, state: str = "COMMENTED") -> dict[str, Any]:
    return {"author": who, "submittedAt": iso(at), "state": state}


def comment(who: dict[str, str], at: datetime) -> dict[str, Any]:
    return {"author": who, "createdAt": iso(at)}


def run(
    nodes: list[dict[str, Any]],
    maintainers: set[str] = MAINTAINERS,
    *,
    now: datetime = NOW,
) -> prt.Report:
    return prt.classify(
        [prt.parse_pr(n) for n in nodes],
        maintainers,
        now,
        repo="org/repo",
        since=date(2026, 7, 1),
        until=date(2026, 9, 30),
        maintainer_source="test",
    )


# --- which event counts as the first response ------------------------------


def test_review_by_maintainer_is_the_response() -> None:
    report = run([node(1, reviews=[review(user("maint"), T0 + timedelta(days=2))])])
    assert len(report.answered) == 1
    assert report.answered[0].response is not None
    assert report.answered[0].response.kind == "review"
    assert report.answered[0].days == pytest.approx(2.0)


def test_comment_only_review_counts() -> None:
    report = run([node(1, reviews=[review(user("maint"), T0 + timedelta(hours=6), "COMMENTED")])])
    assert report.answered[0].hours == pytest.approx(6.0)


def test_conversation_comment_by_maintainer_counts() -> None:
    report = run([node(1, comments=[comment(user("maint"), T0 + timedelta(days=1))])])
    assert report.answered[0].response.kind == "comment"


def test_earliest_of_several_events_wins() -> None:
    n = node(
        1,
        comments=[comment(user("maint"), T0 + timedelta(days=5))],
        reviews=[review(user("maint"), T0 + timedelta(days=3), "APPROVED")],
        merged_by=user("maint"),
        merged_at=T0 + timedelta(days=6),
    )
    report = run([n])
    assert report.answered[0].response.kind == "review"
    assert report.answered[0].days == pytest.approx(3.0)


def test_merge_by_maintainer_without_comment_counts() -> None:
    report = run([node(1, merged_by=user("maint"), merged_at=T0 + timedelta(days=4))])
    assert report.answered[0].response.kind == "merge"
    assert report.answered[0].days == pytest.approx(4.0)


def test_close_by_maintainer_counts() -> None:
    at = T0 + timedelta(days=1, hours=12)
    report = run([node(1, closed_at=at, closed_by=user("maint"))])
    assert report.answered[0].response.kind == "close"
    assert report.answered[0].days == pytest.approx(1.5)


def test_pending_review_without_submission_is_ignored() -> None:
    n = node(1, reviews=[{"author": user("maint"), "submittedAt": None, "state": "PENDING"}])
    report = run([n])
    assert report.waiting and not report.answered


# --- who does not count ------------------------------------------------------


def test_non_maintainer_comment_does_not_count() -> None:
    report = run([node(1, comments=[comment(user("someone"), T0 + timedelta(hours=1))])])
    assert len(report.waiting) == 1
    assert not report.answered


def test_bot_comment_does_not_count_even_under_a_maintainer_login() -> None:
    # Defensive: a bot account whose login happens to be listed as a maintainer.
    report = run([node(1, comments=[comment(user("maint", bot=True), T0 + timedelta(hours=1))])])
    assert len(report.waiting) == 1


def test_authors_own_comment_does_not_count() -> None:
    n = node(1, author=user("alice"), comments=[comment(user("alice"), T0 + timedelta(hours=1))])
    report = run([n], maintainers={"maint", "alice"})
    # alice is a maintainer, so her PR is excluded rather than measured ...
    assert report.maintainer_authored and not report.answered
    # ... and a non-maintainer author commenting on their own PR is still waiting.
    n2 = node(2, author=user("bob"), comments=[comment(user("bob"), T0 + timedelta(hours=1))])
    assert run([n2]).waiting


def test_deleted_account_is_never_a_maintainer() -> None:
    n = node(1, comments=[{"author": None, "createdAt": iso(T0 + timedelta(hours=1))}])
    assert run([n]).waiting


@pytest.mark.parametrize("kind", ["review", "comment", "merge", "close"])
def test_maintainer_responses_match_logins_case_insensitively(kind: str) -> None:
    actor = user("mAiNt")
    at = T0 + timedelta(days=2)
    events: dict[str, Any] = {
        "review": {"reviews": [review(actor, at)]},
        "comment": {"comments": [comment(actor, at)]},
        "merge": {"merged_by": actor, "merged_at": at},
        "close": {"closed_by": actor, "closed_at": at},
    }[kind]
    report = run([node(1, **events)], maintainers={"MaInT"})
    assert report.answered[0].days == pytest.approx(2.0)
    response = report.answered[0].response
    assert response is not None
    assert response.actor.login == "mAiNt"
    assert report.maintainers == ["MaInT"]


def test_first_response_ignores_authors_own_event_with_different_casing() -> None:
    pr = prt.parse_pr(
        node(1, author=user("MaInT"), comments=[comment(user("maint"), T0 + timedelta(days=1))])
    )
    assert prt.first_maintainer_response(pr, {"maint"}) is None


# --- population --------------------------------------------------------------


def test_bot_authored_pr_is_excluded_as_automated() -> None:
    report = run([node(1, author=user("dependabot", bot=True))])
    assert [p.number for p in report.automated] == [1]
    assert report.total == 1
    assert not report.waiting


def test_maintainer_authored_pr_is_excluded_and_counted() -> None:
    report = run([node(1, author=user("maint"))])
    assert [p.number for p in report.maintainer_authored] == [1]
    assert not report.waiting


@pytest.mark.parametrize("author_login,maintainer_login", [("maint", "MAINT"), ("MAINT", "maint")])
def test_maintainer_authored_exclusion_is_case_insensitive(
    author_login: str, maintainer_login: str
) -> None:
    report = run([node(1, author=user(author_login))], maintainers={maintainer_login})
    assert [p.number for p in report.maintainer_authored] == [1]
    assert not report.answered and not report.waiting and not report.closed_unanswered


def test_open_pr_without_response_is_waiting_with_wait_so_far() -> None:
    report = run([node(1, created=T0 + timedelta(days=20))])
    assert report.waiting[0].days == pytest.approx(10.0)


def test_waiting_is_sorted_longest_first() -> None:
    report = run([node(1, created=T0 + timedelta(days=20)), node(2, created=T0)])
    assert [m.pr.number for m in report.waiting] == [2, 1]


def test_closed_by_author_without_response_is_reported_separately() -> None:
    n = node(1, closed_at=T0 + timedelta(days=3), closed_by=user("contrib"))
    report = run([n])
    assert not report.waiting and not report.answered
    assert report.closed_unanswered[0].days == pytest.approx(3.0)


def test_self_merge_by_non_maintainer_is_closed_unanswered_and_marked() -> None:
    n = node(
        1, author=user("ex-maint"), merged_by=user("ex-maint"), merged_at=T0 + timedelta(hours=2)
    )
    report = run([n])
    assert report.closed_unanswered and report.closed_unanswered[0].pr.merged
    assert "merged by a non-maintainer" in prt.render_text(report)


# --- statistics --------------------------------------------------------------


def test_median_over_answered_and_provisional_median_with_waiting() -> None:
    nodes = [
        node(1, reviews=[review(user("maint"), T0 + timedelta(days=1))]),
        node(2, reviews=[review(user("maint"), T0 + timedelta(days=3))]),
        node(3, reviews=[review(user("maint"), T0 + timedelta(days=10))]),
        node(4),  # waiting 30 days
    ]
    report = run(nodes)
    assert report.median_answered_days == pytest.approx(3.0)
    # answered 1, 3, 10 plus waiting 30 -> median of (3, 10)
    assert report.median_with_waiting_days == pytest.approx(6.5)
    assert report.within_target == 2


def test_provisional_median_can_fall_when_waiting_pr_closes_unanswered() -> None:
    answered = node(1, reviews=[review(user("maint"), T0 + timedelta(days=1))])
    before = run([answered, node(2)])
    assert before.median_with_waiting_days == pytest.approx(15.5)
    text = prt.render_text(before)
    assert "Provisional median including current waits" in text
    assert "lower bound" not in text
    data = prt.render_json(before)
    assert data["median_days_with_waiting"] == pytest.approx(15.5)
    assert "median_days_lower_bound" not in data
    assert any("provisional" in caveat and "closed" in caveat for caveat in data["caveats"])

    closed_at = NOW + timedelta(days=1)
    after = run([answered, node(2, closed_at=closed_at, closed_by=user("contrib"))], now=closed_at)
    assert after.median_answered_days == pytest.approx(1.0)
    assert after.median_with_waiting_days == pytest.approx(1.0)
    assert len(after.closed_unanswered) == 1


def test_median_is_none_when_nothing_measured() -> None:
    report = run([node(1, author=user("dependabot", bot=True))])
    assert report.median_answered_days is None
    assert "n/a" in prt.render_text(report)


def test_truncated_pr_is_flagged() -> None:
    n = node(1, reviews=[review(user("maint"), T0 + timedelta(days=1))], review_total=150)
    report = run([n])
    assert report.answered[0].pr.truncated
    assert "more than" in prt.render_text(report)
    assert prt.render_json(report)["answered"][0]["truncated"] is True


@pytest.mark.parametrize("closed", [False, True])
def test_json_flags_incomplete_comments_when_the_first_response_was_not_fetched(
    closed: bool,
) -> None:
    n = node(
        1,
        comments=[comment(user("someone"), T0 + timedelta(hours=1))] * prt.PER_PR_PAGE,
        comment_total=prt.PER_PR_PAGE + 1,
        closed_at=T0 + timedelta(days=20) if closed else None,
        closed_by=user("contrib") if closed else None,
    )
    report = run([n])
    bucket = "closed_unanswered" if closed else "waiting"
    data = prt.render_json(report)
    assert data["counts"][bucket] == 1
    assert data[bucket][0]["truncated"] is True
    assert "only the first page was read: #1" in prt.render_text(report)


# --- output ------------------------------------------------------------------


def test_text_output_states_rules_and_caveats() -> None:
    text = prt.render_text(run([node(1)]))
    assert "Rules applied:" in text
    assert "What the rules get wrong:" in text
    for rule in prt.RULES:
        assert rule in text
    for caveat in prt.CAVEATS:
        assert caveat in text


def test_json_output_round_trips() -> None:
    report = run([node(1, reviews=[review(user("maint"), T0 + timedelta(days=2))]), node(2)])
    data = json.loads(json.dumps(prt.render_json(report)))
    assert data["counts"] == {
        "opened": 2,
        "excluded_automated": 0,
        "excluded_maintainer_authored": 0,
        "answered": 1,
        "waiting": 1,
        "closed_unanswered": 0,
    }
    assert data["median_days_answered"] == 2.0
    assert data["waiting"][0]["number"] == 2
    assert data["waiting"][0]["truncated"] is False
    assert data["answered"][0]["response"]["by"] == "maint"
    assert data["answered"][0]["truncated"] is False
    assert data["rules"] == prt.RULES


def test_parse_time_accepts_github_z_suffix() -> None:
    assert prt.parse_time("2026-07-01T12:00:00Z") == T0


def test_cli_rejects_until_before_since(capsys: pytest.CaptureFixture[str]) -> None:
    assert prt.main(["--since", "2026-09-30", "--until", "2026-07-01"]) == 1
    assert "before" in capsys.readouterr().err


# --- window selection ----------------------------------------------------------


def window(*argv: str) -> tuple[date, date]:
    return prt.resolve_window(prt.build_parser().parse_args(list(argv)), today=date(2026, 10, 16))


def test_quarter_shortcut() -> None:
    assert window("--quarter", "2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert window("--quarter", "2026Q1") == (date(2026, 1, 1), date(2026, 3, 31))
    assert window("--quarter", "2026-q4") == (date(2026, 10, 1), date(2026, 12, 31))


def test_month_shortcut_handles_month_ends_and_year_roll() -> None:
    assert window("--month", "2026-09") == (date(2026, 9, 1), date(2026, 9, 30))
    assert window("--month", "2028-02") == (date(2028, 2, 1), date(2028, 2, 29))
    assert window("--month", "2026-12") == (date(2026, 12, 1), date(2026, 12, 31))


def test_since_defaults_until_to_today() -> None:
    assert window("--since", "2026-10-01") == (date(2026, 10, 1), date(2026, 10, 16))


def test_window_flags_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        prt.build_parser().parse_args(["--month", "2026-09", "--quarter", "2026-Q3"])


def test_bad_month_and_quarter_are_rejected() -> None:
    for argv in (["--month", "2026-13"], ["--quarter", "2026-Q5"], ["--month", "Sept"]):
        with pytest.raises(SystemExit):
            prt.build_parser().parse_args(argv)


def test_cli_requires_a_window(capsys: pytest.CaptureFixture[str]) -> None:
    assert prt.main([]) == 1
    assert "required" in capsys.readouterr().err


def test_cli_rejects_until_without_since(capsys: pytest.CaptureFixture[str]) -> None:
    assert prt.main(["--month", "2026-09", "--until", "2026-09-30"]) == 1
    assert "--until only goes with --since" in capsys.readouterr().err
