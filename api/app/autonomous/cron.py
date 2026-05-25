"""Minimal in-repo five-field cron parser — M4-B3.

The autonomous schedule dispatcher needs to compute the next run time of
a schedule from its ``cron_expr``. The five standard fields — minute,
hour, day-of-month, month, day-of-week — with ``*``, comma lists
(``1,2``), ranges (``1-5``), and steps (``*/5``) cover every shape the
schedule API accepts.

**Why no new dependency (CLAUDE.md SBOM posture):** a full cron library
(``croniter``, ``apscheduler``) is a sizeable SBOM entry and supply-chain
surface for what amounts to five integer-field matchers and a
minute-by-minute forward scan. The forward-scan approach below is small,
fully unit-tested, and has no transitive deps — the trade-off does not
favour pulling in a library. (Per CLAUDE.md "Don't add libraries without
justification".)

Public surface:

* :func:`validate_cron_expr` — raise :class:`ValueError` on a malformed
  expression; called by the schedule create/update endpoints (which map
  the ``ValueError`` to a 422).
* :func:`next_run_after` — the next timezone-aware UTC datetime strictly
  after ``after`` that matches the expression.

The scan walks forward one minute at a time from ``after`` (truncated to
the minute, ``+1`` minute so the result is strictly after ``after``).
A bounded safety ceiling (``_MAX_SCAN_MINUTES`` — just over four years,
covering Feb-29-only schedules) guards against an expression that never
matches; hitting it raises ``ValueError``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NamedTuple

# Field bounds: (min, max) inclusive for each of the five positions.
# day-of-week uses the standard cron convention: Sunday=0 .. Saturday=6,
# with 7 also accepted as Sunday (POSIX crontab compatibility). We map a
# matched cron-dow value to Python's ``datetime.weekday()`` (Mon=0 ..
# Sun=6) in :func:`_matches`.
_FIELD_BOUNDS: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day-of-month
    (1, 12),  # month
    (0, 7),  # day-of-week (cron: Sun=0 or 7 .. Sat=6)
)
_FIELD_NAMES: tuple[str, ...] = (
    "minute",
    "hour",
    "day-of-month",
    "month",
    "day-of-week",
)

# Safety ceiling for the forward scan: ~4 years + slack so a Feb-29-only
# expression still resolves, but a never-matching expression terminates.
_MAX_SCAN_MINUTES = 366 * 4 * 24 * 60 + 24 * 60


def _parse_field(spec: str, lo: int, hi: int, *, field_name: str) -> set[int]:
    """Parse one cron field into the explicit set of integers it matches.

    Supports ``*``, comma lists (``1,2``), ranges (``1-5``), and steps
    (``*/5`` or ``1-30/5``). Raises :class:`ValueError` on any token that
    is malformed or out of the field's ``[lo, hi]`` bounds.
    """

    matched: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            raise ValueError(f"empty token in {field_name} field: {spec!r}")

        # Split off an optional step (``*/5`` or ``1-5/2``).
        step = 1
        body = token
        if "/" in token:
            body, _, step_str = token.partition("/")
            if not step_str.isdigit() or int(step_str) < 1:
                raise ValueError(f"invalid step in {field_name} field: {token!r}")
            step = int(step_str)

        if body == "*":
            start, end = lo, hi
        elif "-" in body:
            start_str, _, end_str = body.partition("-")
            if not (start_str.isdigit() and end_str.isdigit()):
                raise ValueError(f"invalid range in {field_name} field: {token!r}")
            start, end = int(start_str), int(end_str)
        else:
            if not body.isdigit():
                raise ValueError(f"invalid value in {field_name} field: {token!r}")
            start = end = int(body)

        if start > end:
            raise ValueError(f"descending range in {field_name} field: {token!r}")
        if start < lo or end > hi:
            raise ValueError(f"{field_name} value out of bounds [{lo},{hi}] in {token!r}")

        matched.update(range(start, end + 1, step))

    if not matched:
        raise ValueError(f"{field_name} field matched no values: {spec!r}")
    return matched


class _ParsedCron(NamedTuple):
    """Parsed five-field cron expression.

    ``sets`` holds the per-field explicit match sets (minute, hour,
    day-of-month, month, day-of-week). ``dom_restricted`` and
    ``dow_restricted`` record whether the raw day-of-month / day-of-week
    field was something other than ``*`` — needed to implement the
    Vixie/POSIX rule that a *both-restricted* day pair matches on EITHER
    field (see :func:`_matches`).
    """

    sets: tuple[set[int], ...]
    dom_restricted: bool
    dow_restricted: bool


def _parse_cron_expr(cron_expr: str) -> _ParsedCron:
    """Parse a five-field cron string into a :class:`_ParsedCron`.

    Raises :class:`ValueError` if the expression does not have exactly
    five whitespace-separated fields or any field is malformed.
    """

    fields = cron_expr.split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have exactly 5 fields, got {len(fields)}: {cron_expr!r}"
        )
    sets = tuple(
        _parse_field(spec, lo, hi, field_name=name)
        for spec, (lo, hi), name in zip(fields, _FIELD_BOUNDS, _FIELD_NAMES, strict=True)
    )
    # Index 2 = day-of-month, index 4 = day-of-week. A field is "restricted"
    # when its raw spec is not the bare wildcard ``*``.
    return _ParsedCron(
        sets=sets,
        dom_restricted=fields[2].strip() != "*",
        dow_restricted=fields[4].strip() != "*",
    )


def validate_cron_expr(cron_expr: str) -> None:
    """Validate ``cron_expr``; raise :class:`ValueError` if malformed.

    Thin wrapper over :func:`_parse_cron_expr` for the API layer, which
    catches the ``ValueError`` and returns 422.

    Beyond per-field bounds, this also rejects expressions that are
    in-bounds but *unsatisfiable* — e.g. ``0 0 30 2 *`` (Feb 30 never
    occurs) or ``0 0 31 4 *`` (Apr 31). Such an expression would pass the
    field checks, enter the DB, then make :func:`next_run_after` scan the
    whole horizon and raise — wedging the dispatcher when it came due. We
    probe :func:`next_run_after` here and re-raise as a validation error so
    these never reach the DB. Normal expressions resolve in a handful of
    iterations, so create/patch latency is unaffected; only genuinely-never
    expressions pay the full-scan cost and are correctly rejected. Feb 29
    (``0 0 29 2 *``) IS satisfiable — a leap year falls within the scan
    horizon — and is therefore accepted.
    """

    _parse_cron_expr(cron_expr)
    next_run_after(cron_expr, datetime.now(UTC))


def _matches(moment: datetime, parsed: _ParsedCron) -> bool:
    """True if ``moment`` (minute-resolution) satisfies ``parsed``.

    Day-of-month / day-of-week follow the Vixie/POSIX rule: when BOTH
    fields are restricted (neither was ``*``), the day matches on EITHER
    (``dom OR dow``); when only one is restricted, normal AND applies.
    """

    minute_set, hour_set, dom_set, month_set, dow_set = parsed.sets
    # Map Python's weekday() (Mon=0 .. Sun=6) to cron dow (Sun=0 .. Sat=6).
    # Sunday: Python 6 → cron 0; both 0 and 7 in the set mean Sunday.
    cron_dow = (moment.weekday() + 1) % 7
    dom_ok = moment.day in dom_set
    dow_ok = cron_dow in dow_set or (cron_dow == 0 and 7 in dow_set)

    if parsed.dom_restricted and parsed.dow_restricted:
        day_ok = dom_ok or dow_ok
    else:
        day_ok = dom_ok and dow_ok

    return (
        moment.minute in minute_set
        and moment.hour in hour_set
        and moment.month in month_set
        and day_ok
    )


def next_run_after(cron_expr: str, after: datetime) -> datetime:
    """Return the next UTC datetime strictly after ``after`` matching ``cron_expr``.

    ``after`` is normalized to UTC (a naive datetime is assumed UTC). The
    result is minute-truncated, timezone-aware (UTC), and strictly greater
    than ``after``.

    Raises :class:`ValueError` if the expression is malformed or no match
    is found within the bounded scan window (a practically-never-matching
    expression).
    """

    parsed = _parse_cron_expr(cron_expr)

    after = after.replace(tzinfo=UTC) if after.tzinfo is None else after.astimezone(UTC)

    # Truncate to the minute and step one minute forward so the result is
    # strictly after ``after`` (a moment that itself matches is skipped).
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

    for _ in range(_MAX_SCAN_MINUTES):
        if _matches(candidate, parsed):
            return candidate
        candidate += timedelta(minutes=1)

    raise ValueError(f"cron expression {cron_expr!r} produced no run time within the scan window")
