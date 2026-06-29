"""WS-D PR1 — the agentic planner: prompt, decision parser, observation summarizer.

The planner is a gateway inference (ToolIntent.plan) that, given the matter
goal + compact observations + the observe-intent allowlist, returns either the
next governed action to take or a 'done' signal. It NEVER selects outside the
closed allowlist (an out-of-set proposal parses to None → the loop stops
conservatively). It does not execute anything — the loop dispatches its choice
through guarded_tool_call (ADR 0020 D1).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.autonomous.enums import ToolIntent

log = logging.getLogger(__name__)

# The planner may choose ONLY observe intents (gather), or signal done.
# run_skill/run_playbook are reserved for the final synthesis; emit/side-effect
# intents are not planner-driven in PR1.
PLANNER_ALLOWLIST: frozenset[ToolIntent] = frozenset(
    {ToolIntent.retrieve_chunks, ToolIntent.retrieve_caselaw, ToolIntent.call_mcp_tool}
)

_SYSTEM_PROMPT = """\
You are the research planner for a governed legal-matter agent. Given the
MATTER GOAL and the OBSERVATIONS gathered so far, decide the SINGLE next
research action, or that enough has been gathered.

You may choose ONLY from this closed set of actions (you cannot invent tools):
{allowlist}

Respond with STRICTLY VALID JSON, one of:

  {{"next_intent": "<one action above>",
    "args": {{ ...arguments for that action... }},
    "rationale": "<one sentence: why this next step>"}}

or, when enough authority/context has been gathered:

  {{"done": true, "rationale": "<one sentence: why you are finished>"}}

Output ONLY the JSON object. No preamble, no markdown fencing."""


@dataclass(slots=True)
class PlannerDecision:
    done: bool
    next_intent: ToolIntent | None
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


def build_planner_messages(
    *, goal: str, observations: list[str], allowlist: frozenset[ToolIntent]
) -> list[dict[str, str]]:
    allow = ", ".join(sorted(i.value for i in allowlist))
    system = _SYSTEM_PROMPT.format(allowlist=allow)
    obs = "\n".join(f"- {o}" for o in observations) if observations else "(none yet)"
    user = f"MATTER GOAL:\n{goal}\n\nOBSERVATIONS SO FAR:\n{obs}\n\nDecide the next action as JSON."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_planner_decision(content: str | None) -> PlannerDecision | None:
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):  # tolerate an accidental fence
        text = text.strip("`")
        text = text[text.find("{") :] if "{" in text else text
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.info("planner produced non-JSON", extra={"event": "autonomous_planner_malformed"})
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("done") is True:
        return PlannerDecision(
            done=True, next_intent=None, rationale=str(payload.get("rationale", ""))
        )
    raw_intent = payload.get("next_intent")
    if not isinstance(raw_intent, str):
        return None
    try:
        intent = ToolIntent(raw_intent)
    except ValueError:
        return None
    if intent not in PLANNER_ALLOWLIST:
        log.info(
            "planner chose out-of-allowlist intent %r",
            raw_intent,
            extra={"event": "autonomous_planner_out_of_set"},
        )
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        args = {}
    return PlannerDecision(
        done=False,
        next_intent=intent,
        args=args,
        rationale=str(payload.get("rationale", "")),
    )


@dataclass(slots=True)
class EvidenceItem:
    """A numbered piece of gathered authority the synthesis may quote-and-cite.

    ``content`` is the authoritative text used at delivery to verify a quoted
    span (chunk text for kb, opinion text for caselaw). Loop-local + synthesis
    context only — NEVER written to analysis_plan_trace/audit (P3)."""

    n: int
    kind: str  # "kb" | "caselaw"
    ref: str  # chunk_id (kb) | cluster_id (caselaw), as str
    content: str
    display: str


def collect_evidence(intent: ToolIntent, result: object, start_n: int) -> list[EvidenceItem]:
    outcome = getattr(result, "outcome", "success")
    data = getattr(result, "data", None) or {}
    if outcome != "success":
        return []
    items: list[EvidenceItem] = []
    n = start_n
    if intent == ToolIntent.retrieve_chunks:
        for c in data.get("chunks") or []:
            if not isinstance(c, dict) or not c.get("chunk_id"):
                continue
            items.append(
                EvidenceItem(
                    n=n,
                    kind="kb",
                    ref=str(c["chunk_id"]),
                    content=str(c.get("content") or ""),
                    display=f"{c.get('file_name') or '?'} (chunk {c['chunk_id']})",
                )
            )
            n += 1
    elif intent == ToolIntent.retrieve_caselaw:
        rows = data.get("results") or data.get("matches") or []
        for r in rows:
            if not isinstance(r, dict) or not r.get("cluster_id"):
                continue
            items.append(
                EvidenceItem(
                    n=n,
                    kind="caselaw",
                    ref=str(r["cluster_id"]),
                    content=str(r.get("opinion_text") or r.get("text") or ""),
                    display=f"{r.get('case_name') or '?'} ({r.get('court') or '?'} {r.get('date_filed') or '?'})",
                )
            )
            n += 1
    return items


def validate_action_args(intent: ToolIntent, args: dict[str, Any]) -> None:
    """Reject planner-supplied args that would fault at the SQL/handler layer
    BEFORE they reach the chokepoint. Raises ValueError on an un-runnable arg
    so the loop records a clean failed observation instead of poisoning the
    AsyncSession with a DBAPIError (WS-D PR1 C1; ADR 0015 closed-set boundary).
    A clean (no-SQL) ValueError keeps the session usable so synthesis still runs.

    Only validates ``retrieve_chunks`` — the only local/SQL intent in the
    planner allowlist.  ``retrieve_caselaw``/``call_mcp_tool`` are external;
    their handler/HTTP errors are already non-poisoning.
    """
    if intent == ToolIntent.retrieve_chunks:
        top_k = args.get("top_k")
        if top_k is not None and (
            not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1
        ):
            raise ValueError(f"retrieve_chunks top_k must be a positive int, got {top_k!r}")
        emb = args.get("query_embedding")
        if emb is not None and (
            not isinstance(emb, list)
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in emb)
        ):
            raise ValueError("retrieve_chunks query_embedding must be None or a list of numbers")


_SNIPPET = 120


def summarize_observation(intent: ToolIntent, rationale: str, result: object) -> str:
    """One-line, P3-clean summary of a tool result for the planner's context.

    Never includes full opinion/chunk payloads — only counts, ids, case names,
    and short snippets. ``result`` is a guard.ToolResult (duck-typed to avoid a
    circular import: read ``.outcome`` and ``.data``)."""
    outcome = getattr(result, "outcome", "success")
    data = getattr(result, "data", None) or {}
    if outcome != "success":
        return f"{intent.value} → failed ({outcome})"
    if intent == ToolIntent.retrieve_caselaw:
        items = data.get("results") or data.get("matches") or []
        names = [
            f"{(i.get('case_name') or '?')} ({i.get('court') or '?'} {i.get('date_filed') or '?'}; cl={i.get('cluster_id') or '?'})"
            for i in items[:5]
            if isinstance(i, dict)
        ]
        more = "" if len(items) <= 5 else f" +{len(items) - 5} more"
        return f"{intent.value} → {len(items)} result(s): [{'; '.join(names)}]{more}"
    if intent == ToolIntent.retrieve_chunks:
        chunks = data.get("chunks") or []
        files = sorted({fn for c in chunks if isinstance(c, dict) and (fn := c.get("file_name"))})
        return f"{intent.value} → {len(chunks)} chunk(s) from {files or '(no files)'}"
    if intent == ToolIntent.call_mcp_tool:
        payload = data if isinstance(data, dict) else {}
        keys = sorted(payload.keys())[:8]
        return f"{intent.value} → payload keys {keys}"
    snippet = str(data)[:_SNIPPET]
    return f"{intent.value} → {snippet}"
