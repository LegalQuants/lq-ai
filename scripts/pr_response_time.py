#!/usr/bin/env python3
"""Measure the median time to first maintainer response on pull requests.

CONTRIBUTING.md ("Review timelines", adopted by ADR 0034) publishes a
first-response target of 7 days and promises that the measured median is
published beside it. ADR 0030 precondition P3 needs that median under 7 days
for a quarter before a 1.0 date can be set. This script produces the figure
(issue #699).

Definition (ADR 0030 / ADR 0034):

- measured: time from a PR being opened to the first substantive maintainer
  response;
- over: all PRs opened in the window, excluding automated dependency bumps;
- statistic: the median.

The rules this script applies for "maintainer", "substantive" and "dependency
bump" are printed with every run, together with what they get wrong, so the
published number carries its own caveats. See ``RULES`` and ``CAVEATS`` below.

PRs still waiting are the ones that matter most: a median over answered PRs
alone flatters the number. The script therefore lists every PR with no
response yet, with how long each has waited, and also prints a provisional
median that counts those PRs at their current wait. That figure can fall if
a waiting PR closes without a maintainer response and leaves the population.

Usage:

    python scripts/pr_response_time.py --quarter 2026-Q3
    python scripts/pr_response_time.py --month 2026-09
    python scripts/pr_response_time.py --since 2026-07-01 --until 2026-09-30
    python scripts/pr_response_time.py --since 2026-07-01 --json

``--month`` and ``--quarter`` are shortcuts for the two publication cadences
CONTRIBUTING.md contemplates; ``--since``/``--until`` take any range.

Authentication: a read-only GitHub token from ``GITHUB_TOKEN`` or ``GH_TOKEN``,
or, when neither is set, the token ``gh auth token`` prints. Reading the
maintainer team needs the ``read:org`` scope; without it pass
``--maintainer LOGIN`` (repeatable) and the team is not looked up at all.

No dependencies beyond the standard library; ``gh`` is only used to find a
token when none is in the environment.

Exit codes:
    0  — figures printed.
    1  — could not reach GitHub, bad token, or bad arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

GRAPHQL_URL = "https://api.github.com/graphql"
DEFAULT_REPO = "LegalQuants/lq-ai"
DEFAULT_TEAM = "lq-ai-maintainers"
TARGET_DAYS = 7.0
# GitHub's search API stops at 1000 results per query.
SEARCH_RESULT_CAP = 1000
# Per-PR connections fetched in one page. Reviews and comments come back
# oldest-first, so the first maintainer response is in the first page unless a
# PR has more than this many earlier non-maintainer entries.
PER_PR_PAGE = 100

RULES = [
    "Maintainer: a current member of the GitHub team given by --team (default "
    f"{DEFAULT_TEAM}), or the logins given by --maintainer. Membership is read as of "
    "the run, not as of each response. Logins are compared case-insensitively.",
    "Substantive response: the earliest of (a) a review submitted by a maintainer, in any "
    "state, including a comment-only review; (b) a conversation comment by a maintainer; "
    "(c) the maintainer merging the PR; (d) the maintainer closing the PR. Reviews and "
    "comments by bot accounts never count, and the PR's own author never counts as "
    "responding to it.",
    "Automated dependency bump: any PR whose author is a bot account (for example "
    "dependabot). Excluded from the population before anything is measured.",
    "Maintainer-authored PRs are excluded from the measured population and counted "
    "separately: with one maintainer, nobody else is in a position to respond, so they "
    "would otherwise wait forever and distort the number in the other direction.",
    "Clock: starts at the PR's creation time, draft or not, and stops at the first "
    "substantive response. Times are UTC. The window is inclusive of both dates and "
    "selects PRs by creation date.",
]

CAVEATS = [
    "A one-line 'thanks, will look' comment counts the same as a full review; the rule "
    "measures attention, not depth.",
    "Team membership is read today. Responses by someone who has since left the team are "
    "not counted; responses by someone who joined after the window are counted.",
    "Organisation owners and trusted reviewers who are not on the maintainers team do not "
    "count, even when their review was the one that unblocked the PR.",
    "Reactions, labels, assignment, review requests, and edits to the PR description are "
    "not counted as responses.",
    "A PR opened as a draft is clocked from creation, not from when it was marked ready "
    "for review.",
    "A PR a bot opened for a reason other than a dependency bump is still excluded, and a "
    "human-opened dependency bump is still measured.",
    "PRs closed without any maintainer response are listed separately. They are not in "
    "the median, which is one more way the median can flatter the picture. A PR in that "
    "list that was merged was merged by someone with write access who is not on the "
    "team today.",
    "The median including current waits is provisional: PRs closed without a maintainer "
    "response drop out, so the final median can be lower.",
    f"Only the first {PER_PR_PAGE} reviews and {PER_PR_PAGE} comments of each PR are read; "
    "a PR is flagged if it has more.",
]

PR_QUERY = """
query($q: String!, $first: Int!, $after: String, $perPr: Int!) {
  search(query: $q, type: ISSUE, first: $first, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number title url createdAt isDraft merged mergedAt closedAt
        author { __typename login }
        mergedBy { __typename login }
        reviews(first: $perPr) {
          totalCount
          nodes { author { __typename login } submittedAt state }
        }
        comments(first: $perPr) {
          totalCount
          nodes { author { __typename login } createdAt }
        }
        timelineItems(first: 20, itemTypes: [CLOSED_EVENT]) {
          nodes { ... on ClosedEvent { createdAt actor { __typename login } } }
        }
      }
    }
  }
}
"""

TEAM_QUERY = """
query($org: String!, $team: String!, $after: String) {
  organization(login: $org) {
    team(slug: $team) {
      members(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { login }
      }
    }
  }
}
"""


class GitHubError(RuntimeError):
    """The GitHub API refused or failed a request."""


@dataclass(frozen=True)
class Actor:
    login: str
    is_bot: bool


@dataclass(frozen=True)
class Event:
    """Something a person did on a PR that might count as a response."""

    kind: str  # review | comment | merge | close
    actor: Actor
    at: datetime


@dataclass
class PullRequest:
    number: int
    title: str
    url: str
    created_at: datetime
    author: Actor
    is_draft: bool
    merged: bool
    closed_at: datetime | None
    events: list[Event] = field(default_factory=list)
    truncated: bool = False


@dataclass
class Measured:
    pr: PullRequest
    response: Event | None
    hours: float  # to first response, or waited so far / until close

    @property
    def days(self) -> float:
        return self.hours / 24.0


@dataclass
class Report:
    repo: str
    since: date
    until: date
    now: datetime
    maintainers: list[str]
    maintainer_source: str
    automated: list[PullRequest]
    maintainer_authored: list[PullRequest]
    answered: list[Measured]
    waiting: list[Measured]
    closed_unanswered: list[Measured]

    @property
    def total(self) -> int:
        return (
            len(self.automated)
            + len(self.maintainer_authored)
            + len(self.answered)
            + len(self.waiting)
            + len(self.closed_unanswered)
        )

    @property
    def median_answered_days(self) -> float | None:
        return _median_days(self.answered)

    @property
    def median_with_waiting_days(self) -> float | None:
        """Provisional median counting waiting PRs at their current wait.

        Waiting PRs can leave the measured population by closing unanswered,
        so the final answered-only median can be lower than this snapshot.
        """
        return _median_days(self.answered + self.waiting)

    @property
    def within_target(self) -> int:
        return sum(1 for m in self.answered if m.days <= TARGET_DAYS)


# --------------------------------------------------------------------------
# Parsing and classification (pure; exercised by scripts/tests)
# --------------------------------------------------------------------------


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _actor(node: dict[str, Any] | None) -> Actor:
    # A deleted account comes back as null; it can never be a maintainer.
    if not node:
        return Actor(login="ghost", is_bot=False)
    return Actor(login=node["login"], is_bot=node.get("__typename") == "Bot")


def parse_pr(node: dict[str, Any]) -> PullRequest:
    """Turn one GraphQL PullRequest node into a PullRequest with its events."""
    created = parse_time(node["createdAt"])
    pr = PullRequest(
        number=node["number"],
        title=node["title"],
        url=node["url"],
        created_at=created,
        author=_actor(node.get("author")),
        is_draft=bool(node.get("isDraft")),
        merged=bool(node.get("merged")),
        closed_at=parse_time(node["closedAt"]) if node.get("closedAt") else None,
    )
    reviews = node.get("reviews") or {}
    for review in reviews.get("nodes") or []:
        if not review.get("submittedAt"):  # pending review, never submitted
            continue
        pr.events.append(
            Event("review", _actor(review.get("author")), parse_time(review["submittedAt"]))
        )
    comments = node.get("comments") or {}
    for comment in comments.get("nodes") or []:
        pr.events.append(
            Event("comment", _actor(comment.get("author")), parse_time(comment["createdAt"]))
        )
    if node.get("mergedAt"):
        pr.events.append(Event("merge", _actor(node.get("mergedBy")), parse_time(node["mergedAt"])))
    for item in (node.get("timelineItems") or {}).get("nodes") or []:
        if item and item.get("createdAt"):
            pr.events.append(
                Event("close", _actor(item.get("actor")), parse_time(item["createdAt"]))
            )
    more_reviews = reviews.get("totalCount", 0) > len(reviews.get("nodes") or [])
    more_comments = comments.get("totalCount", 0) > len(comments.get("nodes") or [])
    pr.truncated = more_reviews or more_comments
    return pr


def first_maintainer_response(pr: PullRequest, maintainers: set[str]) -> Event | None:
    """The earliest event that counts as a substantive maintainer response."""
    maintainer_logins = {login.casefold() for login in maintainers}
    author_login = pr.author.login.casefold()
    candidates = [
        e
        for e in pr.events
        if e.actor.login.casefold() in maintainer_logins
        and not e.actor.is_bot
        and e.actor.login.casefold() != author_login
        and e.at >= pr.created_at
    ]
    return min(candidates, key=lambda e: e.at) if candidates else None


def _hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0


def classify(
    prs: list[PullRequest],
    maintainers: set[str],
    now: datetime,
    *,
    repo: str,
    since: date,
    until: date,
    maintainer_source: str,
) -> Report:
    maintainer_logins = {login.casefold() for login in maintainers}
    report = Report(
        repo=repo,
        since=since,
        until=until,
        now=now,
        maintainers=sorted(maintainers),
        maintainer_source=maintainer_source,
        automated=[],
        maintainer_authored=[],
        answered=[],
        waiting=[],
        closed_unanswered=[],
    )
    for pr in sorted(prs, key=lambda p: p.created_at):
        if pr.author.is_bot:
            report.automated.append(pr)
            continue
        if pr.author.login.casefold() in maintainer_logins:
            report.maintainer_authored.append(pr)
            continue
        response = first_maintainer_response(pr, maintainer_logins)
        if response is not None:
            report.answered.append(
                Measured(pr, response, _hours_between(pr.created_at, response.at))
            )
        elif pr.closed_at is None:
            report.waiting.append(Measured(pr, None, _hours_between(pr.created_at, now)))
        else:
            report.closed_unanswered.append(
                Measured(pr, None, _hours_between(pr.created_at, pr.closed_at))
            )
    report.waiting.sort(key=lambda m: -m.hours)
    return report


def _median_days(items: list[Measured]) -> float | None:
    if not items:
        return None
    return statistics.median(m.hours for m in items) / 24.0


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _fmt_days(value: float | None) -> str:
    return "n/a (no PRs)" if value is None else f"{value:.1f} days"


def _pr_line(m: Measured) -> str:
    flags = ""
    if m.pr.is_draft:
        flags += " (draft)"
    if m.pr.merged:
        flags += " (merged by a non-maintainer)"
    return f"  #{m.pr.number:<5} {m.days:6.1f} days  {m.pr.author.login:<24} {m.pr.title}{flags}"


def render_text(report: Report) -> str:
    lines = [
        f"PR first-response times: {report.repo}, PRs opened {report.since} to {report.until} (UTC)",
        f"Measured at {report.now.strftime('%Y-%m-%d %H:%M')} UTC",
        f"Maintainers ({report.maintainer_source}): {', '.join(report.maintainers) or 'none'}",
        "",
        f"PRs opened in window:                      {report.total}",
        f"  excluded, automated dependency bumps:    {len(report.automated)}",
        f"  excluded, opened by a maintainer:        {len(report.maintainer_authored)}",
        f"  measured:                                {len(report.answered) + len(report.waiting) + len(report.closed_unanswered)}",
        f"    answered:                              {len(report.answered)}",
        f"    still waiting (open, no response):     {len(report.waiting)}",
        f"    closed with no maintainer response:    {len(report.closed_unanswered)}",
        "",
        f"Median time to first maintainer response (answered PRs):   {_fmt_days(report.median_answered_days)}",
        f"Provisional median including current waits: {_fmt_days(report.median_with_waiting_days)}",
    ]
    if report.answered:
        share = 100.0 * report.within_target / len(report.answered)
        lines.append(
            f"Target (CONTRIBUTING.md): {TARGET_DAYS:.0f} days; answered within target: "
            f"{report.within_target} of {len(report.answered)} ({share:.0f}%)"
        )
    lines.append("")
    lines.append("Still waiting for a first maintainer response:")
    if report.waiting:
        lines.extend(_pr_line(m) for m in report.waiting)
    else:
        lines.append("  none")
    if report.closed_unanswered:
        lines.append("")
        lines.append(
            "Closed without a maintainer response (time open shown; not in the median; "
            "a merged entry was merged by someone who is not on the team today):"
        )
        lines.extend(_pr_line(m) for m in report.closed_unanswered)
    truncated = [
        m.pr for m in report.answered + report.waiting + report.closed_unanswered if m.pr.truncated
    ]
    if truncated:
        lines.append("")
        lines.append(
            f"Warning: {len(truncated)} PR(s) have more than {PER_PR_PAGE} reviews or comments; "
            "only the first page was read: " + ", ".join(f"#{p.number}" for p in truncated)
        )
    lines.append("")
    lines.append("Rules applied:")
    lines.extend(f"  - {rule}" for rule in RULES)
    lines.append("")
    lines.append("What the rules get wrong:")
    lines.extend(f"  - {caveat}" for caveat in CAVEATS)
    return "\n".join(lines) + "\n"


def _measured_json(m: Measured) -> dict[str, Any]:
    return {
        "number": m.pr.number,
        "title": m.pr.title,
        "url": m.pr.url,
        "author": m.pr.author.login,
        "draft": m.pr.is_draft,
        "merged": m.pr.merged,
        "truncated": m.pr.truncated,
        "created_at": m.pr.created_at.isoformat(),
        "days": round(m.days, 2),
        "response": (
            {"kind": m.response.kind, "by": m.response.actor.login, "at": m.response.at.isoformat()}
            if m.response
            else None
        ),
    }


def render_json(report: Report) -> dict[str, Any]:
    return {
        "repo": report.repo,
        "window": {"since": report.since.isoformat(), "until": report.until.isoformat()},
        "measured_at": report.now.isoformat(),
        "maintainers": report.maintainers,
        "maintainer_source": report.maintainer_source,
        "target_days": TARGET_DAYS,
        "counts": {
            "opened": report.total,
            "excluded_automated": len(report.automated),
            "excluded_maintainer_authored": len(report.maintainer_authored),
            "answered": len(report.answered),
            "waiting": len(report.waiting),
            "closed_unanswered": len(report.closed_unanswered),
        },
        "median_days_answered": _round(report.median_answered_days),
        "median_days_with_waiting": _round(report.median_with_waiting_days),
        "answered_within_target": report.within_target,
        "waiting": [_measured_json(m) for m in report.waiting],
        "closed_unanswered": [_measured_json(m) for m in report.closed_unanswered],
        "answered": [_measured_json(m) for m in report.answered],
        "excluded_automated": [p.number for p in report.automated],
        "excluded_maintainer_authored": [p.number for p in report.maintainer_authored],
        "rules": RULES,
        "caveats": CAVEATS,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


# --------------------------------------------------------------------------
# GitHub access (network; not unit-tested)
# --------------------------------------------------------------------------


def find_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitHubError(
            "no token: set GITHUB_TOKEN or GH_TOKEN, or log in with `gh auth login`"
        ) from exc
    token = result.stdout.strip()
    if not token:
        raise GitHubError("`gh auth token` printed nothing; set GITHUB_TOKEN instead")
    return token


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "lq-ai-pr-response-time",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise GitHubError(
            f"GitHub returned HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubError(f"could not reach GitHub: {exc.reason}") from exc
    if payload.get("errors"):
        raise GitHubError(
            "GraphQL error: " + "; ".join(e.get("message", "?") for e in payload["errors"])
        )
    return payload["data"]


def fetch_team(token: str, org: str, team: str) -> set[str]:
    members: set[str] = set()
    after: str | None = None
    while True:
        data = graphql(token, TEAM_QUERY, {"org": org, "team": team, "after": after})
        node = (data.get("organization") or {}).get("team")
        if node is None:
            raise GitHubError(
                f"team {org}/{team} not found or not visible to this token (needs read:org); "
                "pass --maintainer LOGIN instead"
            )
        members.update(m["login"] for m in node["members"]["nodes"])
        page = node["members"]["pageInfo"]
        if not page["hasNextPage"]:
            return members
        after = page["endCursor"]


def fetch_prs(token: str, repo: str, since: date, until: date) -> list[PullRequest]:
    q = f"repo:{repo} is:pr created:{since.isoformat()}..{until.isoformat()}"
    prs: list[PullRequest] = []
    after: str | None = None
    while True:
        data = graphql(token, PR_QUERY, {"q": q, "first": 50, "after": after, "perPr": PER_PR_PAGE})
        search = data["search"]
        if search["issueCount"] > SEARCH_RESULT_CAP:
            raise GitHubError(
                f"{search['issueCount']} PRs match, over GitHub's {SEARCH_RESULT_CAP}-result search "
                "cap; narrow the window"
            )
        prs.extend(parse_pr(node) for node in search["nodes"] if node)
        if not search["pageInfo"]["hasNextPage"]:
            return prs
        after = search["pageInfo"]["endCursor"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a YYYY-MM-DD date") from exc


def _parse_month(value: str) -> tuple[date, date]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise argparse.ArgumentTypeError(f"{value!r} is not a YYYY-MM month")
    year, month = int(match.group(1)), int(match.group(2))
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return first, last


def _parse_quarter(value: str) -> tuple[date, date]:
    match = re.fullmatch(r"(\d{4})-?[Qq]([1-4])", value)
    if not match:
        raise argparse.ArgumentTypeError(f"{value!r} is not a YYYY-Qn quarter")
    year, quarter = int(match.group(1)), int(match.group(2))
    first = date(year, 3 * quarter - 2, 1)
    last = _parse_month(f"{year}-{3 * quarter:02d}")[1]
    return first, last


def resolve_window(args: argparse.Namespace, today: date) -> tuple[date, date]:
    """Pick the creation-date window from --quarter, --month, or --since/--until."""
    if args.quarter:
        return args.quarter
    if args.month:
        return args.month
    if args.since is None:
        raise ValueError("one of --quarter, --month or --since is required")
    until = args.until or today
    if until < args.since:
        raise ValueError("--until is before --since")
    return args.since, until


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Median time to first maintainer response on PRs opened in a window (#699).",
    )
    window = parser.add_mutually_exclusive_group()
    window.add_argument(
        "--quarter", type=_parse_quarter, metavar="YYYY-Qn", help="a calendar quarter, e.g. 2026-Q3"
    )
    window.add_argument(
        "--month", type=_parse_month, metavar="YYYY-MM", help="a calendar month, e.g. 2026-09"
    )
    window.add_argument(
        "--since",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="first creation date of a custom range",
    )
    parser.add_argument(
        "--until",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="last creation date of a custom range (default: today); only with --since",
    )
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help=f"owner/name (default: {DEFAULT_REPO})"
    )
    parser.add_argument(
        "--team", default=DEFAULT_TEAM, help=f"maintainer team slug (default: {DEFAULT_TEAM})"
    )
    parser.add_argument(
        "--maintainer",
        action="append",
        default=[],
        metavar="LOGIN",
        help="treat LOGIN as a maintainer instead of reading the team; repeatable",
    )
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON instead of text"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(UTC)
    if args.until and args.since is None:
        print("error: --until only goes with --since", file=sys.stderr)
        return 1
    try:
        since, until = resolve_window(args, now.date())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if "/" not in args.repo:
        print("error: --repo must be owner/name", file=sys.stderr)
        return 1
    org = args.repo.split("/", 1)[0]

    try:
        token = find_token()
        if args.maintainer:
            maintainers = set(args.maintainer)
            source = "given with --maintainer"
        else:
            maintainers = fetch_team(token, org, args.team)
            source = f"team {org}/{args.team}, read at run time"
        prs = fetch_prs(token, args.repo, since, until)
    except GitHubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = classify(
        prs,
        maintainers,
        now,
        repo=args.repo,
        since=since,
        until=until,
        maintainer_source=source,
    )
    if args.json:
        json.dump(render_json(report), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
