"""Citation Engine Stage 4 — ensemble verification tests (M2-D1).

``verify_ensemble(candidate, document, *, gateway, ensemble_config)``
runs the Stage 3 paraphrase judge in parallel against N models and
aggregates verdicts under the operator-chosen rule. These tests cover:

* **Strict aggregation**: all judges must verify; any miss → MISS.
  ``partial=True`` on the result when any judge said partial.
* **Majority aggregation**: simple majority of verified verdicts wins;
  ties (≤ n/2) miss conservatively. ``partial=True`` on dissent OR
  any partial judge.
* **Tier envelope propagation**: ``ensemble_config.envelope_tier``
  copies onto the result regardless of outcome.
* **Confidence**: mean across verified judges' confidences.
* **Empty judge_models**: short-circuits to MISS.
* **Cascade routing in :func:`verify`**: ensemble replaces Stage 3
  when ``ensemble_config`` is supplied; falls back to Stage 3 when not.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal

import pytest

from app.citation.verification import (
    VerificationResult,
    verify,
    verify_ensemble,
)
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

# ---------------------------------------------------------------------------
# Stubs.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StubDocument:
    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _StubCandidate:
    source_file_id: uuid.UUID
    source_document_id: uuid.UUID
    source_offset_start: int
    source_offset_end: int
    source_page: int | None
    source_text: str


@dataclass(slots=True)
class _StubEnsembleConfig:
    judge_models: tuple[str, ...]
    aggregation_rule: Literal["strict", "majority"]
    envelope_tier: int | None = 3


class _StubGateway:
    """Returns a different canned response per chat_completion call.

    The verdict list cycles through ``response_contents`` in order so
    a 3-judge ensemble with 3 entries delivers a deterministic
    per-judge verdict — tests can assert on aggregation behavior
    without mocking out call dispatch.
    """

    def __init__(self, *, response_contents: list[str | None]) -> None:
        self._response_contents = response_contents
        self.call_count = 0
        self.requests: list[ChatCompletionRequest] = []

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        idx = self.call_count
        self.call_count += 1
        self.requests.append(request)
        content = self._response_contents[idx % len(self._response_contents)]
        return ChatCompletionResponse(
            id=f"chatcmpl-judge-{idx}",
            created=0,
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


def _judge_json(
    *,
    verdict: str,
    confidence: str = "high",
    justification: str = "test",
) -> str:
    return json.dumps(
        {"verdict": verdict, "confidence": confidence, "justification": justification}
    )


def _doc(text: str = "The agreement was signed on the third of June.") -> _StubDocument:
    return _StubDocument(id=uuid.uuid4(), normalized_content=text)


def _candidate(
    doc: _StubDocument, *, source_text: str = "the agreement was signed"
) -> _StubCandidate:
    return _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=min(40, len(doc.normalized_content)),
        source_page=None,
        source_text=source_text,
    )


def _ensemble(
    *,
    n: int = 3,
    rule: Literal["strict", "majority"] = "strict",
    envelope_tier: int | None = 3,
) -> _StubEnsembleConfig:
    return _StubEnsembleConfig(
        judge_models=tuple(f"judge-{i}" for i in range(n)),
        aggregation_rule=rule,
        envelope_tier=envelope_tier,
    )


# ---------------------------------------------------------------------------
# Strict aggregation.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_strict_all_yes_verified_not_partial() -> None:
    """Strict + every judge says yes → verified, partial=False, method='ensemble_strict'."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 3)
    doc = _doc()
    cand = _candidate(doc)
    cfg = _ensemble(n=3, rule="strict")

    result = await verify_ensemble(cand, doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.method == "ensemble_strict"
    assert result.partial is False
    assert result.confidence == pytest.approx(0.90)
    assert result.tier_envelope == 3
    assert gw.call_count == 3


@pytest.mark.unit
async def test_strict_one_no_misses() -> None:
    """Strict + one judge says no → MISS (no row persisted)."""

    gw = _StubGateway(
        response_contents=[
            _judge_json(verdict="yes"),
            _judge_json(verdict="no"),
            _judge_json(verdict="yes"),
        ]
    )
    cfg = _ensemble(n=3, rule="strict")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is False
    assert result.method is None


@pytest.mark.unit
async def test_strict_all_yes_with_one_partial_persists_partial_flag() -> None:
    """Strict-verified but at least one judge said partial → verified, partial=True."""

    gw = _StubGateway(
        response_contents=[
            _judge_json(verdict="yes"),
            _judge_json(verdict="partial"),
            _judge_json(verdict="yes"),
        ]
    )
    cfg = _ensemble(n=3, rule="strict")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.partial is True
    assert result.method == "ensemble_strict"


# ---------------------------------------------------------------------------
# Majority aggregation.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_majority_three_of_three_verified_not_partial() -> None:
    """Majority + all agree → verified, partial=False."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 3)
    cfg = _ensemble(n=3, rule="majority")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.method == "ensemble_majority"
    assert result.partial is False


@pytest.mark.unit
async def test_majority_two_of_three_verified_marks_partial_for_dissent() -> None:
    """Majority + 2/3 verified → verified with partial=True (dissent flagged)."""

    gw = _StubGateway(
        response_contents=[
            _judge_json(verdict="yes"),
            _judge_json(verdict="no"),
            _judge_json(verdict="yes"),
        ]
    )
    cfg = _ensemble(n=3, rule="majority")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.method == "ensemble_majority"
    assert result.partial is True
    # Confidence is mean of the verified judges' confidences (both
    # high → 0.90).
    assert result.confidence == pytest.approx(0.90)


@pytest.mark.unit
async def test_majority_one_of_three_misses() -> None:
    """Majority + only 1/3 verified → MISS (not strict majority)."""

    gw = _StubGateway(
        response_contents=[
            _judge_json(verdict="no"),
            _judge_json(verdict="no"),
            _judge_json(verdict="yes"),
        ]
    )
    cfg = _ensemble(n=3, rule="majority")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is False


@pytest.mark.unit
async def test_majority_tied_two_of_four_misses() -> None:
    """Majority + 2/4 → MISS (strict-majority rule: > n/2)."""

    gw = _StubGateway(
        response_contents=[
            _judge_json(verdict="yes"),
            _judge_json(verdict="no"),
            _judge_json(verdict="yes"),
            _judge_json(verdict="no"),
        ]
    )
    cfg = _ensemble(n=4, rule="majority")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is False


# ---------------------------------------------------------------------------
# Tier-envelope propagation + edge cases.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_tier_envelope_propagates_when_verified() -> None:
    """``ensemble_config.envelope_tier`` copies onto the verified result."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 2)
    cfg = _ensemble(n=2, rule="strict", envelope_tier=4)
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.tier_envelope == 4


@pytest.mark.unit
async def test_tier_envelope_null_when_gateway_reported_no_tier() -> None:
    """``envelope_tier=None`` propagates onto the result (no per-row override)."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 2)
    cfg = _ensemble(n=2, rule="strict", envelope_tier=None)
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.tier_envelope is None


@pytest.mark.unit
async def test_empty_judge_models_misses_without_calling_gateway() -> None:
    """No-judges config is a misconfiguration; short-circuit to MISS."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")])
    cfg = _StubEnsembleConfig(judge_models=(), aggregation_rule="strict", envelope_tier=3)
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is False
    assert gw.call_count == 0


@pytest.mark.unit
async def test_ensemble_judge_calls_carry_anonymize_false_for_correctness() -> None:
    """M2-D4 integration edge: every ensemble judge call opts out of anonymization.

    The Stage 3 :func:`verify_paraphrase` request sets
    ``anonymize=False`` (see verification.py docstring: "the judge needs
    to see actual content to verify it; anonymized text would destroy
    the semantics"). Ensemble dispatches multiple Stage 3 calls in
    parallel; each one carries the same opt-out. This test pins the
    contract: provider sees the real cited claim + chunk on every
    ensemble judge dispatch even when chat-level anonymization is
    active for the originating message.

    Why this composition works: anonymization happens at the
    chat-completion request level (per-request flag). Ensemble judge
    calls are SEPARATE chat-completion requests dispatched by the api/
    after the original chat response is persisted. Each judge request
    is independently routed, anonymization-gated, and audit-logged by
    the gateway. The api/-side ``anonymize=False`` flag forces the
    middleware to skip pseudonymization regardless of the gateway's
    default config.
    """

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 3)
    cfg = _ensemble(n=3, rule="strict")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert gw.call_count == 3
    for req in gw.requests:
        assert req.anonymize is False, (
            f"every ensemble judge request must set anonymize=False; "
            f"got anonymize={req.anonymize!r} on model={req.model!r}"
        )


@pytest.mark.unit
async def test_confidence_is_mean_of_verified_judges() -> None:
    """Mixed confidences average: high(0.90) + medium(0.70) = 0.80 mean."""

    gw = _StubGateway(
        response_contents=[
            _judge_json(verdict="yes", confidence="high"),
            _judge_json(verdict="yes", confidence="medium"),
        ]
    )
    cfg = _ensemble(n=2, rule="strict")
    doc = _doc()

    result = await verify_ensemble(_candidate(doc), doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.confidence == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Cascade routing in verify().
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_verify_routes_to_ensemble_when_config_supplied() -> None:
    """``verify(..., ensemble_config=cfg)`` runs Stage 4 instead of Stage 3."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 2)
    cfg = _ensemble(n=2, rule="strict")
    doc = _doc("Unrelated content; exact + tolerant miss.")
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=20,
        source_page=None,
        # Source text doesn't match the doc slice — Stages 1+2 miss
        # and the cascade should route to Stage 4.
        source_text="the agreement was signed last June",
    )

    result = await verify(cand, doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.method == "ensemble_strict"
    assert gw.call_count == 2


@pytest.mark.unit
async def test_verify_falls_back_to_stage_3_when_no_ensemble_config() -> None:
    """No ensemble_config kwarg → Stage 3 (single judge)."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")])
    doc = _doc("Unrelated content; exact + tolerant miss.")
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=20,
        source_page=None,
        source_text="the agreement was signed last June",
    )

    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.method == "paraphrase_judge"
    assert gw.call_count == 1


@pytest.mark.unit
async def test_verify_short_circuits_on_exact_match_even_with_ensemble_config() -> None:
    """Stage 1 wins; Stage 4 never dispatches (no judge calls)."""

    gw = _StubGateway(response_contents=[_judge_json(verdict="yes")] * 3)
    cfg = _ensemble(n=3, rule="strict")
    doc = _doc("the agreement was signed on the third of June.")
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=24,
        source_page=None,
        source_text="the agreement was signed",
    )

    result = await verify(cand, doc, gateway=gw, ensemble_config=cfg)

    assert result.verified is True
    assert result.method == "exact_match"
    # Stage 4 never ran — Stage 1's byte-equality short-circuit hit.
    assert gw.call_count == 0


@pytest.mark.unit
async def test_verify_returns_miss_without_gateway_even_with_ensemble_config() -> None:
    """``gateway=None`` short-circuits past both Stage 3 and Stage 4."""

    cfg = _ensemble(n=3, rule="strict")
    doc = _doc("Unrelated content; exact + tolerant miss.")
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=10,
        source_page=None,
        source_text="completely different text",
    )

    result = await verify(cand, doc, gateway=None, ensemble_config=cfg)

    assert result == VerificationResult(
        verified=False, method=None, confidence=None, partial=False, tier_envelope=None
    )


# ---------------------------------------------------------------------------
# _resolve_ensemble_config — activation + cost-budget pre-flight.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StubResolvedEnsembleConfig:
    """Mirrors :class:`app.clients.gateway.EnsembleConfig`."""

    default_enabled: bool
    judge_models: tuple[str, ...]
    aggregation_rule: Literal["strict", "majority"]
    max_cost_per_message_usd: float
    envelope_tier: int | None


class _StubGatewayForActivation:
    """Returns a canned :class:`EnsembleConfig` from get_citation_engine_ensemble_config."""

    def __init__(self, *, config: _StubResolvedEnsembleConfig | None) -> None:
        self._config = config
        self.fetch_count = 0

    async def get_citation_engine_ensemble_config(self) -> _StubResolvedEnsembleConfig | None:
        self.fetch_count += 1
        return self._config


@dataclass(slots=True)
class _StubSkill:
    """Mirrors :class:`app.skills.schema.Skill` for the activation check."""

    ensemble_verification: bool | None


class _StubSkillRegistry:
    """Returns canned :class:`_StubSkill` objects by name."""

    def __init__(self, skills: dict[str, _StubSkill]) -> None:
        self._skills = skills

    def get_skill(self, name: str) -> _StubSkill | None:
        return self._skills.get(name)


@pytest.fixture
def _activation_config_off() -> _StubResolvedEnsembleConfig:
    """Gateway has ensemble configured but default_enabled=False."""

    return _StubResolvedEnsembleConfig(
        default_enabled=False,
        judge_models=("fast", "smart"),
        aggregation_rule="strict",
        max_cost_per_message_usd=0.05,
        envelope_tier=3,
    )


@pytest.mark.unit
async def test_resolve_activates_on_skill_flag(
    _activation_config_off: _StubResolvedEnsembleConfig,
) -> None:
    """Skill frontmatter ensemble_verification:true activates Stage 4."""

    from app.api.chats import _resolve_ensemble_config

    gw = _StubGatewayForActivation(config=_activation_config_off)
    registry = _StubSkillRegistry({"nda-review": _StubSkill(ensemble_verification=True)})

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=["nda-review"],
        project_ensemble_verification=False,
        skill_registry=registry,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is not None
    assert result.judge_models == ("fast", "smart")


@pytest.mark.unit
async def test_resolve_activates_on_project_flag(
    _activation_config_off: _StubResolvedEnsembleConfig,
) -> None:
    """Project ensemble_verification:true activates Stage 4."""

    from app.api.chats import _resolve_ensemble_config

    gw = _StubGatewayForActivation(config=_activation_config_off)

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=[],
        project_ensemble_verification=True,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is not None


@pytest.mark.unit
async def test_resolve_activates_on_gateway_default() -> None:
    """Gateway default_enabled:true activates Stage 4 with no other signal."""

    from app.api.chats import _resolve_ensemble_config

    cfg = _StubResolvedEnsembleConfig(
        default_enabled=True,
        judge_models=("fast", "smart"),
        aggregation_rule="strict",
        max_cost_per_message_usd=0.05,
        envelope_tier=3,
    )
    gw = _StubGatewayForActivation(config=cfg)

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=[],
        project_ensemble_verification=False,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is not None


@pytest.mark.unit
async def test_resolve_no_activation_returns_none(
    _activation_config_off: _StubResolvedEnsembleConfig,
) -> None:
    """No skill, no project, gateway default off → None (no Stage 4)."""

    from app.api.chats import _resolve_ensemble_config

    gw = _StubGatewayForActivation(config=_activation_config_off)

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=[],
        project_ensemble_verification=False,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is None


@pytest.mark.unit
async def test_resolve_returns_none_when_gateway_missing() -> None:
    """gateway=None means Stage 4 cannot run regardless of activation."""

    from app.api.chats import _resolve_ensemble_config

    result = await _resolve_ensemble_config(
        gateway=None,
        applied_skills=["nda-review"],
        project_ensemble_verification=True,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is None


@pytest.mark.unit
async def test_resolve_returns_none_when_gateway_has_no_ensemble_config() -> None:
    """Gateway with no ensemble configured (None) → None (no Stage 4)."""

    from app.api.chats import _resolve_ensemble_config

    gw = _StubGatewayForActivation(config=None)

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=[],
        project_ensemble_verification=True,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is None


@pytest.mark.unit
async def test_resolve_cost_budget_fallback_returns_none() -> None:
    """Estimated cost > max_cost_per_message_usd → None (fall back to Stage 3)."""

    from app.api.chats import _resolve_ensemble_config

    # 100 candidates * 3 judges * $0.005/judge = $1.50 estimated.
    # Budget of $0.05 -> estimate exceeds, fall back.
    cfg = _StubResolvedEnsembleConfig(
        default_enabled=True,
        judge_models=("a", "b", "c"),
        aggregation_rule="strict",
        max_cost_per_message_usd=0.05,
        envelope_tier=3,
    )
    gw = _StubGatewayForActivation(config=cfg)

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=[],
        project_ensemble_verification=False,
        skill_registry=None,
        n_candidates=100,
        message_id=uuid.uuid4(),
    )

    assert result is None


@pytest.mark.unit
async def test_resolve_cost_budget_within_cap_activates() -> None:
    """Estimated cost ≤ budget → ensemble activates."""

    from app.api.chats import _resolve_ensemble_config

    # 2 candidates * 3 judges * $0.005 = $0.030 estimated < $0.05 budget.
    cfg = _StubResolvedEnsembleConfig(
        default_enabled=True,
        judge_models=("a", "b", "c"),
        aggregation_rule="strict",
        max_cost_per_message_usd=0.05,
        envelope_tier=3,
    )
    gw = _StubGatewayForActivation(config=cfg)

    result = await _resolve_ensemble_config(
        gateway=gw,
        applied_skills=[],
        project_ensemble_verification=False,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
    )

    assert result is not None
