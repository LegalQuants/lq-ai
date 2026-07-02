"""Tolerant structured-output parser for the autonomous executor — M4 real-work.

Single responsibility: parse the analysis call's response content into a
:class:`StructuredResult`. Tolerant by design — a malformed response
becomes a graceful ``is_structured=False`` result with ``raw_content``
preserved, NOT an exception. The drafting node uses ``is_structured`` to
decide whether to dispatch per-finding/memory/precedent calls or a single
``emit_finding`` fallback with the raw text.

This satisfies the inline contract in
:mod:`api.app.autonomous.prompts` above ``STRUCTURED_OUTPUT_INSTRUCTION``:
the parser MUST implement the malformed-response fallback (tolerant
unstructured result with raw content preserved) — never raise.

Tolerance is item-level too: in the dict-shaped arrays (``findings``,
``suggested_memories``, ``suggested_precedents``, ``artifacts``), any
non-dict item is silently dropped rather than passed through to the
drafting node's ``.get()`` calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# Matches a fenced JSON block: ```json { ... } ``` or ``` { ... } ```.
# DOTALL so the JSON body may span newlines; the inner group captures the
# braces so json.loads receives only the object.
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class StructuredResult:
    """Result of parsing the analysis call's response content.

    The four dict-shaped arrays (``findings``, ``suggested_memories``,
    ``suggested_precedents``, ``artifacts``) contain dicts ONLY — any
    non-dict items the model emitted are silently dropped at parse time
    (tolerant parsing). The string arrays (``privilege_concerns``,
    ``scope_concerns``) keep items as-is; they are only ever
    string-formatted downstream.

    Attributes:
        is_structured: True iff a JSON object was successfully parsed.
        findings: Parsed ``findings`` array (empty when missing).
        suggested_memories: Parsed ``suggested_memories`` array.
        suggested_precedents: Parsed ``suggested_precedents`` array.
        privilege_concerns: Parsed ``privilege_concerns`` array.
        scope_concerns: Parsed ``scope_concerns`` array.
        artifacts: Parsed ``artifacts`` array (Donna ask #8 — items shaped
            ``{"name", "content_md"}`` per ``ARTIFACT_OUTPUT_INSTRUCTION``).
            Parsed regardless of the session's ``emit_artifacts`` opt-in
            flag — the parser is flag-agnostic; the drafting node enforces
            opt-in and ignores this list when the flag is off.
        raw_content: Original response content, preserved verbatim.
            When ``is_structured`` is False this is the text the drafting
            node logs as a single fallback finding.
    """

    is_structured: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    suggested_memories: list[dict[str, Any]] = field(default_factory=list)
    suggested_precedents: list[dict[str, Any]] = field(default_factory=list)
    privilege_concerns: list[str] = field(default_factory=list)
    scope_concerns: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    raw_content: str = ""

    @classmethod
    def unstructured(cls, raw: str | None) -> StructuredResult:
        """Build the tolerant fallback result with the raw text preserved."""
        return cls(is_structured=False, raw_content=raw or "")


def _as_list(value: Any) -> list[Any]:
    """Coerce a JSON value to a list — non-list values yield []."""
    return list(value) if isinstance(value, list) else []


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    """Coerce a JSON value to a list of dicts — tolerant, item-level.

    Non-list values yield []; non-dict items inside a list are silently
    dropped. The dict-shaped arrays (``suggested_memories``,
    ``suggested_precedents``, ``artifacts``) are consumed downstream with
    ``.get()`` calls, so a string or number smuggled into an otherwise
    valid array would raise ``AttributeError`` in the drafting node and
    fail the whole run — worse than this module's tolerant-degradation
    contract allows. This helper intentionally hardens the three
    pre-existing dict-shaped loops too, not just ``artifacts``: a uniform
    posture beats per-loop drift (the failure mode is not "wrong decision"
    but "different decisions in different files").

    Note: ``findings`` use :func:`_normalize_findings` instead, which
    additionally sanitizes the ``citations`` key on each finding (WS-D PR2).
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_findings(value: Any) -> list[dict[str, Any]]:
    """Coerce the ``findings`` array and sanitize per-finding ``citations``.

    Like :func:`_as_dict_list`, but additionally processes each finding to
    produce a sanitized ``citations`` list (WS-D PR2):

    * Non-dict items in the top-level list are dropped (same as _as_dict_list).
    * Each finding gets a ``citations`` key set to a sanitized list of dicts
      ``{"quote": str, "source": int}`` built from the raw ``citations``
      value.  Any entry that is not a dict, has a non-str ``quote``, has a
      non-int ``source``, or has a bool ``source`` (booleans are ints in
      Python / JSON but semantically wrong here) is silently dropped.
    * Absent ``citations`` key → empty list (``[]``).

    This function never raises — it is part of the tolerant-parse contract.
    """
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        finding: dict[str, Any] = dict(item)
        raw_citations = finding.get("citations")
        citations: list[dict[str, Any]] = []
        if isinstance(raw_citations, list):
            for c in raw_citations:
                if (
                    isinstance(c, dict)
                    and isinstance(c.get("quote"), str)
                    and isinstance(c.get("source"), int)
                    and not isinstance(c.get("source"), bool)
                ):
                    citations.append({"quote": c["quote"], "source": c["source"]})
        finding["citations"] = citations
        result.append(finding)
    return result


def parse_structured_output(content: str | None) -> StructuredResult:
    """Parse the analysis call's response into a :class:`StructuredResult`.

    Order of attempts:

    1. Find a ``` ```json ... ``` ``` (or unlabeled ```` ``` ````) fenced
       JSON block; parse the captured object.
    2. Try :func:`json.loads` on the whole stripped content.
    3. Return :meth:`StructuredResult.unstructured` with the raw content.

    A successfully-parsed result fills missing arrays with ``[]``. Any
    top-level JSON value that is not an object (lists, strings, numbers,
    booleans, null) is treated as unstructured.

    This function NEVER raises on malformed input — the contract from
    :mod:`api.app.autonomous.prompts` requires a tolerant return so the
    drafting node can always emit at least a single fallback finding.
    """
    if not content:
        return StructuredResult.unstructured(content)

    parsed: dict[str, Any] | None = None

    match = _FENCED_JSON_RE.search(content)
    if match:
        try:
            candidate = json.loads(match.group(1))
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict):
            parsed = candidate

    if parsed is None:
        try:
            candidate = json.loads(content.strip())
        except json.JSONDecodeError:
            return StructuredResult.unstructured(content)
        if not isinstance(candidate, dict):
            return StructuredResult.unstructured(content)
        parsed = candidate

    return StructuredResult(
        is_structured=True,
        findings=_normalize_findings(parsed.get("findings")),
        suggested_memories=_as_dict_list(parsed.get("suggested_memories")),
        suggested_precedents=_as_dict_list(parsed.get("suggested_precedents")),
        privilege_concerns=_as_list(parsed.get("privilege_concerns")),
        scope_concerns=_as_list(parsed.get("scope_concerns")),
        artifacts=_as_dict_list(parsed.get("artifacts")),
        raw_content=content,
    )


__all__ = ["StructuredResult", "parse_structured_output"]
