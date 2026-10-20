"""DE-240 — live adversarial-extraction test (maintainer-run, opt-in).

End-to-end check of the response path: can a prompt trick the model
into revealing a pseudonymized original? The fixtures
(``extraction/extraction_prompts.json``) plant synthetic PII and then
ask for a TRANSFORMED rendering of it (reversed, letter-spelled,
base64, ...). Because the gateway rehydrates pseudonyms in responses,
a transformed rendering is the only observable that distinguishes "the
provider saw the raw PII" from a legitimate round-trip —
``test_fixture_integrity.py`` enforces that property deterministically.

This test needs a running gateway with anonymization enabled and a
real provider behind it, so it is guarded twice and skips by default:

* ``LQ_PII_LIVE=1`` must be set (the explicit opt-in), and
* ``LQ_PII_GATEWAY_URL`` must point at the gateway (e.g.
  ``http://127.0.0.1:8100``).

Optional: ``LQ_PII_MODEL`` (default ``smart``), ``LQ_PII_GATEWAY_TOKEN``
(sent as a Bearer token when the deployment requires auth).

Maintainer run (documented in docs/quality/pii-leakage-rates.md):

    LQ_PII_LIVE=1 LQ_PII_GATEWAY_URL=http://127.0.0.1:8100 \
        pytest tests/pii/test_extraction_live.py -m live -rs

A failure means a leak indicator appeared in a model response — treat
it as a confidentiality incident signal and investigate the
anonymization path before anything else. Model outputs are
nondeterministic; a PASS is evidence, not proof.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

FIXTURES_PATH = Path(__file__).resolve().parent / "extraction" / "extraction_prompts.json"

_LIVE_ENABLED = os.environ.get("LQ_PII_LIVE") == "1"
_GATEWAY_URL = os.environ.get("LQ_PII_GATEWAY_URL", "").rstrip("/")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (_LIVE_ENABLED and _GATEWAY_URL),
        reason="live extraction test: set LQ_PII_LIVE=1 and LQ_PII_GATEWAY_URL to run",
    ),
]


def _fixtures() -> list[dict[str, Any]]:
    with FIXTURES_PATH.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    fixtures: list[dict[str, Any]] = data["fixtures"]
    return fixtures


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: str(f["id"]))
async def test_extraction_attack_reveals_no_transformed_original(
    fixture: dict[str, Any],
) -> None:
    import httpx

    headers = {"Content-Type": "application/json"}
    token = os.environ.get("LQ_PII_GATEWAY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "model": os.environ.get("LQ_PII_MODEL", "smart"),
        "messages": [
            {"role": "user", "content": fixture["setup_content"]},
            {"role": "user", "content": fixture["attack_content"]},
        ],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{_GATEWAY_URL}/v1/chat/completions", json=payload, headers=headers
        )
    assert response.status_code == 200, f"gateway returned {response.status_code}: {response.text}"

    body = response.json()
    content = " ".join(
        choice.get("message", {}).get("content") or "" for choice in body.get("choices", [])
    )

    leaks = [ind for ind in fixture["leak_indicators"] if ind in content]
    assert not leaks, (
        f"{fixture['id']}: leak indicator(s) {leaks} appeared in the model response — "
        f"the provider may have seen the raw PII. Response content: {content!r}"
    )
