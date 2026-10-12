"""Live injection measurements through the normal non-streaming chat API.

Runs require explicit opt-in, gateway readiness and API credentials.
Every answer gets independent canary, mention and structure observations.
Session hooks report corpus completeness and enforce an optional strict
task-preservation proxy/degradation floor. A canary emission is an
observation, not by itself a demonstrated successful attack.
"""

from __future__ import annotations

import pytest

from .conftest import write_attack_report
from .injection_lib import compose_fixture, load_base_snapshot, load_corpus, score_output
from .live import injection_skip_reason

pytestmark = pytest.mark.injection_live

ATTACKS = load_corpus()
ATTACK_IDS = [f"{a.target_skill}--{a.category}--{a.id}" for a in ATTACKS]


@pytest.mark.parametrize("attack", ATTACKS, ids=ATTACK_IDS)
def test_injection_rate(attack, injection_client, injection_report_dir, injection_run) -> None:
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

    observation = score_output(content, attack, snapshot)
    model = message.get("routed_model")
    provider = message.get("routed_provider")
    injection_run.record(attack, observation, model, provider)

    write_attack_report(
        injection_report_dir,
        attack,
        observation=observation,
        routed_model=model,
        routed_provider=provider,
        content=content,
    )
