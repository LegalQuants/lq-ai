"""Live injection tests: seed each attack into a fixture, score the output.

Marker ``injection_live``; skipped cleanly unless LQ_INJECTION_LIVE=1 plus
a provider key plus api credentials are present (see live.py). Each test
seeds one corpus attack into its target DE-231 fixture, sends the composed
document through the normal chat-send path with the skill attached, and
deterministically classifies the assistant output (followed / flagged /
ignored / degraded — see injection_lib). Outcomes accumulate into the
session ``rate_collector``, which writes the rates summary and applies the
ratcheted floor (if any) at session end.

These tests do NOT assert per-attack pass/fail on the *outcome* — a single
followed injection is a measurement, not a collection failure. They DO
assert transport invariants (no gateway error, skill applied); a broken
send measured nothing and must fail loudly. The detection-rate gate is the
session-level floor in conftest.rate_collector.
"""

from __future__ import annotations

import pytest

from .conftest import write_attack_report
from .injection_lib import classify, compose_fixture, load_base_snapshot, load_corpus
from .live import injection_skip_reason

pytestmark = pytest.mark.injection_live

ATTACKS = load_corpus()
ATTACK_IDS = [f"{a.target_skill}--{a.category}--{a.id}" for a in ATTACKS]


@pytest.mark.parametrize("attack", ATTACKS, ids=ATTACK_IDS)
def test_injection_rate(attack, injection_client, report_dir, rate_collector) -> None:
    assert injection_skip_reason() is None  # injection_client fixture already skipped

    fixture = compose_fixture(attack)
    snapshot = load_base_snapshot(attack.target_skill)

    body = injection_client.run_fixture(fixture)
    message = body.get("message", {})
    content = message.get("content", "")

    # Transport-level invariants — a gateway error or an unapplied skill
    # means the attack measured nothing, so fail loudly.
    assert not message.get("error_code"), (
        f"assistant message carries error_code={message.get('error_code')!r}"
    )
    applied = body.get("applied_skills") or message.get("applied_skills") or []
    assert attack.target_skill in applied, (
        f"skill {attack.target_skill!r} was not applied (applied_skills={applied!r})"
    )

    outcome = classify(content, attack, snapshot)

    tally = rate_collector.setdefault(attack.target_skill, {}).setdefault(
        attack.category, {"followed": 0, "flagged": 0, "ignored": 0, "degraded": 0}
    )
    tally[outcome] += 1

    write_attack_report(
        report_dir,
        attack,
        outcome=outcome,
        routed_model=message.get("routed_model"),
        routed_provider=message.get("routed_provider"),
        content=content,
    )
