"""Live golden tests: run each acceptance fixture through the stack (DE-231).

Marker ``golden_live``; skipped cleanly unless LQ_GOLDEN_LIVE=1 plus a
provider key plus api credentials are present (see live_client). Each
test sends one fixture through the normal chat-send path with the skill
attached, structurally evaluates the assistant's markdown against the
fixture's golden snapshot, and always writes a machine-readable report
(pass or fail) to the report dir — the nightly workflow turns failing
reports into a release-blocking issue.

Record mode (``LQ_GOLDEN_RECORD=1``): range misses do NOT fail the test;
observed values are written to ``snapshots/<id>.observed.json`` beside
the golden for maintainer review. This is how provisional snapshots get
calibrated — observed numbers come only from real runs, never authored
by hand.
"""

from __future__ import annotations

import json
import warnings

import pytest

from .conftest import write_report
from .golden_lib import discover_pairs, evaluate, load_fixture, load_snapshot
from .live_client import live_config, live_skip_reason

pytestmark = pytest.mark.golden_live

PAIRS = discover_pairs()
PAIR_IDS = [f"{p.skill}--{p.fixture_id}" for p in PAIRS]


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_skill_golden(pair, golden_client, report_dir) -> None:
    assert live_skip_reason() is None  # golden_client fixture already skipped
    config = live_config()
    if config.skills_filter is not None and pair.skill not in config.skills_filter:
        pytest.skip(f"skill {pair.skill!r} not in LQ_GOLDEN_SKILLS filter")

    fixture = load_fixture(pair.fixture_path)
    snapshot = load_snapshot(pair.snapshot_path)

    body = golden_client.run_fixture(fixture)
    message = body.get("message", {})
    content = message.get("content", "")

    # Transport-level invariants — these fail even in record mode: a
    # gateway error or an unapplied skill means the run measured nothing.
    assert not message.get("error_code"), (
        f"assistant message carries error_code={message.get('error_code')!r}"
    )
    applied = body.get("applied_skills") or message.get("applied_skills") or []
    assert pair.skill in applied, (
        f"skill {pair.skill!r} was not applied to the turn (applied_skills={applied!r})"
    )

    result = evaluate(snapshot, content)
    report_payload = {
        "fixture": pair.fixture_id,
        "skill": pair.skill,
        "snapshot": str(pair.snapshot_path.relative_to(pair.snapshot_path.parents[3])),
        "snapshot_status": snapshot.status,
        "record_mode": config.record,
        "routed_model": message.get("routed_model"),
        "routed_provider": message.get("routed_provider"),
        "result": result.to_dict(),
    }
    report_path = write_report(report_dir, f"{pair.skill}--{pair.fixture_id}", report_payload)

    if config.record:
        observed_path = pair.snapshot_path.with_name(f"{pair.fixture_id}.observed.json")
        observed_path.write_text(
            json.dumps(
                {
                    "fixture": pair.fixture_id,
                    "skill": pair.skill,
                    "note": (
                        "Observed values from a live run (LQ_GOLDEN_RECORD=1) for "
                        "maintainer calibration of the provisional golden snapshot. "
                        "Review, fold into the .golden.json ranges, flip status to "
                        "'calibrated', then delete this sidecar."
                    ),
                    "routed_model": message.get("routed_model"),
                    "routed_provider": message.get("routed_provider"),
                    "observed": result.observed,
                    "response_content": content,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if not result.passed:
            warnings.warn(
                f"record mode: {pair.skill}/{pair.fixture_id} misses provisional "
                f"ranges ({len(result.failures)} checks); observed sidecar written "
                f"to {observed_path}",
                stacklevel=1,
            )
        return

    assert result.passed, (
        f"structural golden mismatch for {pair.skill}/{pair.fixture_id} "
        f"(snapshot status: {snapshot.status}); failing checks: "
        + "; ".join(
            f"{f.check} expected {f.expected}, observed {f.observed}" for f in result.failures
        )
        + f"; machine-readable report: {report_path}"
    )
