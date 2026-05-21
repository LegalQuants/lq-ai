"""Assemble a drafted playbook from clustered clauses — M3-A6 Phase 4.

Takes the :class:`Cluster` list from :mod:`.clustering` and emits a
:class:`PlaybookCreate` ready to validate + persist. Per cluster:

* The modal clause becomes ``standard_language``.
* The neighbor clauses become candidate fallback tiers (ranked
  1..N by distance — most-different first).
* One LLM call writes the ``description``, ``redline_strategy``,
  and ``severity_if_missing`` from the clause set ("describe this
  position" round).
* One LLM call per fallback tier writes the tier ``description``
  (why this language is an acceptable alternative).
* ``detection_keywords`` derive from the issue label + recurring
  content words across the cluster's clauses.
* ``detection_examples`` are the modal + neighbor clause_texts
  verbatim — the M3-A2 executor uses these for retrieval.

Output is a :class:`PlaybookCreate`. The wizard's worker validates
it via Pydantic and persists via the same path the manual POST
endpoint uses (so the row + positions go through the same audit
trail). The user-attorney then reviews + edits via the Step 3
inline editor (Phase 6) before final save.

Per the 2026-05-19 quality-bar reframe: this module's output is a
*starting point*, not a polished deliverable. Wrong severity, off
redline strategy, weak descriptions — all expected outputs that the
user-attorney corrects during the edit pass.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Final

from app.clients.gateway import GatewayClient
from app.playbooks.easy.clustering import Cluster
from app.playbooks.easy.extractor import DEFAULT_JUDGE_MODEL
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest
from app.schemas.playbooks import (
    FallbackTier,
    PlaybookCreate,
    PositionCreate,
    PositionSeverity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------


DESCRIBE_POSITION_MAX_TOKENS: Final[int] = 600
"""Max tokens for the per-cluster "describe this position" call.
Output is description + redline_strategy + severity_if_missing —
short structured JSON; 600 tokens is generous without letting a
chatty model run away."""

DESCRIBE_TIER_MAX_TOKENS: Final[int] = 250
"""Max tokens for the per-fallback-tier "why is this acceptable"
call. Short prose — 250 tokens is plenty."""

MAX_KEYWORD_COUNT: Final[int] = 8
"""Cap on ``detection_keywords`` per position. The M3-A2 executor
uses these for lexical FTS retrieval; more than ~8 dilutes the
signal (every clause matches at least one keyword on a long contract)."""

_VALID_SEVERITIES: Final[frozenset[str]] = frozenset({"critical", "high", "medium", "low"})
"""Matches the CHECK constraint on ``playbook_positions.severity_if_missing``
and the :class:`PositionSeverity` literal."""


# A small inline stop-word list. We deliberately avoid pulling NLTK or
# spaCy just for this — keyword derivation is best-effort and the
# downstream user-attorney edits anyway.
_KEYWORD_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "shall",
        "such",
        "that",
        "the",
        "to",
        "under",
        "upon",
        "was",
        "were",
        "which",
        "with",
        "without",
        "this",
    }
)

# Recognize alphabetic word tokens; drop punctuation, numbers, and
# punctuation-attached articles. Multi-word phrases land as separate
# tokens — fine for FTS keyword retrieval.
_KEYWORD_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_DESCRIBE_POSITION_SYSTEM_PROMPT = """\
You are the Playbook Easy Assembly skill — an internal step in the
Easy Playbook generation pipeline. You read a set of clauses that
ALL address the same contract issue (the same position across
multiple agreements) and produce three short, structured fields:

* ``description`` — one sentence explaining what this position is
  and why a playbook would include it. Plain English; no jargon.
* ``redline_strategy`` — one or two sentences telling a contract
  reviewer how to push the contract toward this position when it
  deviates. Concrete and action-oriented.
* ``severity_if_missing`` — one of ``"critical" | "high" | "medium" | "low"``,
  per:
    - ``critical`` — absence likely causes material financial /
      legal / business risk (LoL absent, indemnification absent in
      M&A, IP assignment absent in employment).
    - ``high`` — absence causes meaningful but bounded risk
      (no audit rights in a service contract, no termination-for-
      convenience window).
    - ``medium`` — absence is non-ideal but routine (no governing
      law specified, no notice-period specification).
    - ``low`` — present-vs-absent is mostly a quality-of-life
      drafting concern.

Bias toward ``medium``. False ``critical`` ratings train operators
to ignore the severity signal; calibration is the user-attorney's
job downstream.

Output STRICTLY VALID JSON in this exact shape:

  {"description": "<one sentence>",
   "redline_strategy": "<one or two sentences>",
   "severity_if_missing": "critical" | "high" | "medium" | "low"}

This is INTERMEDIATE output — the user-attorney edits all three
fields during the playbook's review step. Don't agonize over phrasing.
"""


_DESCRIBE_TIER_SYSTEM_PROMPT = """\
You are the Playbook Easy Assembly skill — generating per-fallback-tier
descriptions for the Easy Playbook generation pipeline. You read:

* The org's STANDARD position language on a contract issue.
* An ALTERNATIVE clause (from a prior contract) that addresses the
  same issue with different terms.

Produce one short ``description`` (one sentence) explaining what
makes this alternative acceptable as a fallback. Examples:

* "Twelve-month cap on liability instead of the standard six months."
* "Mutual indemnification scoped to IP infringement only, not all
  third-party claims."
* "Confidentiality term reduced from five years to three years."

Output STRICTLY VALID JSON:

  {"description": "<one short sentence>"}

If the alternative is so similar to the standard that there's no
meaningful difference to describe, say so plainly:

  {"description": "Minor wording variation; substantively equivalent."}

This is INTERMEDIATE output — the user-attorney edits the description
downstream.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def assemble_playbook(
    *,
    clusters: list[Cluster],
    name: str,
    contract_type: str,
    gateway: GatewayClient,
    description: str = "",
    version: str = "1.0.0",
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> PlaybookCreate:
    """Build a :class:`PlaybookCreate` from clustered clauses.

    For each cluster, dispatches:

    * 1 LLM call to the describe-position prompt → fills
      ``description``, ``redline_strategy``, ``severity_if_missing``.
    * N LLM calls to the describe-tier prompt (one per neighbor
      clause) → fills each fallback tier's ``description``.

    Empty cluster list returns a playbook with no positions — valid
    against :class:`PlaybookCreate` but uninteresting. The wizard's
    UI will surface a "no positions detected" state in Phase 6.

    Args:
        clusters: per-issue clusters from :func:`.clustering.cluster_clauses_by_issue`.
        name: playbook name; the wizard's Step 1 collects this.
        contract_type: contract family the playbook applies to
            ("NDA", "MSA-SaaS", etc.); free-form per the schema.
        gateway: inference gateway client.
        description: optional playbook-level description. Defaults
            to empty string.
        version: playbook version. Defaults to ``"1.0.0"``.
        judge_model: gateway model alias for the LLM calls.
    """

    positions: list[PositionCreate] = []
    for order, cluster in enumerate(clusters):
        position = await _build_position(
            cluster=cluster,
            position_order=order,
            gateway=gateway,
            judge_model=judge_model,
            contract_type=contract_type,
        )
        positions.append(position)

    return PlaybookCreate(
        name=name,
        contract_type=contract_type,
        description=description,
        version=version,
        positions=positions,
    )


# ---------------------------------------------------------------------------
# Internal — one position from one cluster
# ---------------------------------------------------------------------------


async def _build_position(
    *,
    cluster: Cluster,
    position_order: int,
    gateway: GatewayClient,
    judge_model: str,
    contract_type: str,
) -> PositionCreate:
    """Produce one :class:`PositionCreate` from one :class:`Cluster`."""

    # Describe-position round (1 LLM call).
    described = await _describe_position(
        cluster=cluster,
        gateway=gateway,
        judge_model=judge_model,
        contract_type=contract_type,
    )

    # Fallback tiers (N LLM calls).
    fallback_tiers: list[FallbackTier] = []
    for rank, neighbor in enumerate(cluster.neighbor_clauses, start=1):
        tier_desc = await _describe_tier(
            modal_text=cluster.modal_clause.clause_text,
            tier_text=neighbor.clause_text,
            gateway=gateway,
            judge_model=judge_model,
            contract_type=contract_type,
        )
        fallback_tiers.append(
            FallbackTier(
                rank=rank,
                description=tier_desc,
                language=neighbor.clause_text,
            )
        )

    detection_keywords = _derive_keywords(
        issue_label=cluster.issue_label,
        clause_texts=[c.clause_text for c in cluster.member_clauses],
    )
    detection_examples = _derive_examples(cluster=cluster)

    return PositionCreate(
        issue=cluster.issue_label,
        description=described["description"],
        standard_language=cluster.modal_clause.clause_text,
        fallback_tiers=fallback_tiers,
        redline_strategy=described["redline_strategy"],
        severity_if_missing=described["severity"],
        detection_keywords=detection_keywords,
        detection_examples=detection_examples,
        position_order=position_order,
    )


# ---------------------------------------------------------------------------
# LLM dispatch
# ---------------------------------------------------------------------------


async def _describe_position(
    *,
    cluster: Cluster,
    gateway: GatewayClient,
    judge_model: str,
    contract_type: str,
) -> dict[str, Any]:
    """Run the describe-position LLM call; return parsed {description, redline_strategy, severity}.

    On failure (transport, malformed JSON, missing fields), returns
    defensive defaults rather than propagating — the user-attorney
    edits the field downstream regardless.
    """

    body_lines = [
        f"CONTRACT TYPE: {contract_type}",
        f"ISSUE: {cluster.issue_label}",
        "",
        "CLAUSES ON THIS ISSUE (one per prior contract):",
    ]
    for index, member in enumerate(cluster.member_clauses):
        body_lines.append(f"\n[CLAUSE {index + 1}]\n{member.clause_text}")
    user_content = "\n".join(body_lines)

    payload = await _dispatch_structured_call(
        gateway=gateway,
        model=judge_model,
        system_prompt=_DESCRIBE_POSITION_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=DESCRIBE_POSITION_MAX_TOKENS,
        purpose="playbook_easy_assemble_describe_position",
    )

    description = _coerce_str(payload.get("description"))
    redline_strategy = _coerce_str(payload.get("redline_strategy"))
    severity = _coerce_severity(payload.get("severity_if_missing"))
    return {
        "description": description,
        "redline_strategy": redline_strategy,
        "severity": severity,
    }


async def _describe_tier(
    *,
    modal_text: str,
    tier_text: str,
    gateway: GatewayClient,
    judge_model: str,
    contract_type: str,
) -> str:
    """Run the describe-tier LLM call; return one-sentence description.

    Defensive fallback on failure: returns ``"Variant clause; review during playbook edit."``
    so the produced playbook is still structurally valid (every fallback tier
    needs a description). The user-attorney edits downstream.
    """

    user_content = (
        f"CONTRACT TYPE: {contract_type}\n\n"
        f"STANDARD LANGUAGE:\n{modal_text}\n\n"
        f"ALTERNATIVE CLAUSE:\n{tier_text}"
    )

    payload = await _dispatch_structured_call(
        gateway=gateway,
        model=judge_model,
        system_prompt=_DESCRIBE_TIER_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=DESCRIBE_TIER_MAX_TOKENS,
        purpose="playbook_easy_assemble_describe_tier",
    )
    description = _coerce_str(payload.get("description"))
    if not description:
        return "Variant clause; review during playbook edit."
    return description


async def _dispatch_structured_call(
    *,
    gateway: GatewayClient,
    model: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    purpose: str,
) -> dict[str, Any]:
    """Dispatch one structured-JSON LLM call; return the parsed dict ({} on any failure).

    Same pattern as :mod:`app.playbooks.nodes._dispatch_structured_call`
    (M3-A2): determinism is left to the model (Opus 4.x reasoning
    models reject explicit `temperature` as of 2026-05; the gateway
    only forwards non-None values, so omitting it is the correct
    posture for both reasoning and sampled models); anonymization off
    (the clause text needs to round-trip verbatim); ``lq_ai_purpose``
    for cost-routing telemetry attribution.
    """

    request = ChatCompletionRequest(
        model=model,
        messages=[
            ChatCompletionMessage(role="system", content=system_prompt),
            ChatCompletionMessage(role="user", content=user_content),
        ],
        max_tokens=max_tokens,
        anonymize=False,
        lq_ai_purpose=purpose,
    )

    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        logger.warning(
            "easy_assemble: gateway call failed; falling back to defaults",
            extra={
                "event": "easy_assemble_gateway_error",
                "purpose": purpose,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return {}

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError):
        return {}
    if not isinstance(content, str) or not content.strip():
        return {}
    return _parse_structured_json(content)


def _parse_structured_json(content: str) -> dict[str, Any]:
    """Lenient JSON parse — strip a leading ``json`` code fence if present."""

    stripped = content.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```", 2)
        if len(parts) >= 2:
            stripped = parts[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.rstrip("`").strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning(
            "easy_assemble: malformed JSON in LLM response",
            extra={
                "event": "easy_assemble_malformed_json",
                "error": str(exc),
            },
        )
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_severity(value: Any) -> PositionSeverity:
    """Normalize severity to a valid enum; default to ``"medium"``.

    Per the prompt's "bias toward medium" guidance, the defensive
    default also lands at medium — keeps the playbook's overall
    severity distribution from being skewed by parse-failure noise.
    """

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _VALID_SEVERITIES:
            return normalized  # type: ignore[return-value]
    return "medium"


# ---------------------------------------------------------------------------
# Keyword + example derivation (deterministic; no LLM)
# ---------------------------------------------------------------------------


def _derive_keywords(*, issue_label: str, clause_texts: list[str]) -> list[str]:
    """Build the ``detection_keywords`` list for a position.

    Combines:

    * Word tokens from the issue label (e.g., "Limitation of Liability"
      → "limitation", "liability"; stop words dropped).
    * Top recurring content words across the cluster's clauses.

    Lowercased, deduplicated (preserving first-occurrence order),
    capped at :data:`MAX_KEYWORD_COUNT`. The M3-A2 executor uses these
    for lexical FTS retrieval; too many keywords dilutes the signal,
    too few misses the clause on long contracts.
    """

    seen: set[str] = set()
    out: list[str] = []

    for token in _tokenize_for_keywords(issue_label):
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= MAX_KEYWORD_COUNT:
            return out

    counts: Counter[str] = Counter()
    for clause in clause_texts:
        for token in set(_tokenize_for_keywords(clause)):
            counts[token] += 1

    for token, _count in counts.most_common():
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= MAX_KEYWORD_COUNT:
            break

    return out


def _tokenize_for_keywords(text: str) -> list[str]:
    """Tokenize ``text`` for keyword derivation: 3+ alphabetic chars, lowercase, stop words dropped."""

    return [
        token.lower()
        for token in _KEYWORD_TOKEN_RE.findall(text)
        if token.lower() not in _KEYWORD_STOPWORDS
    ]


def _derive_examples(*, cluster: Cluster) -> list[str]:
    """Build the ``detection_examples`` list — modal first, then neighbors verbatim."""

    out = [cluster.modal_clause.clause_text]
    for neighbor in cluster.neighbor_clauses:
        out.append(neighbor.clause_text)
    return out
