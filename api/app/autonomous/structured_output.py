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

    Attributes:
        is_structured: True iff a JSON object was successfully parsed.
        findings: Parsed ``findings`` array (empty when missing).
        suggested_memories: Parsed ``suggested_memories`` array.
        suggested_precedents: Parsed ``suggested_precedents`` array.
        privilege_concerns: Parsed ``privilege_concerns`` array.
        scope_concerns: Parsed ``scope_concerns`` array.
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
    raw_content: str = ""

    @classmethod
    def unstructured(cls, raw: str | None) -> StructuredResult:
        """Build the tolerant fallback result with the raw text preserved."""
        return cls(is_structured=False, raw_content=raw or "")


def _as_list(value: Any) -> list[Any]:
    """Coerce a JSON value to a list — non-list values yield []."""
    return list(value) if isinstance(value, list) else []


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
        findings=_as_list(parsed.get("findings")),
        suggested_memories=_as_list(parsed.get("suggested_memories")),
        suggested_precedents=_as_list(parsed.get("suggested_precedents")),
        privilege_concerns=_as_list(parsed.get("privilege_concerns")),
        scope_concerns=_as_list(parsed.get("scope_concerns")),
        raw_content=content,
    )


__all__ = ["StructuredResult", "parse_structured_output"]
