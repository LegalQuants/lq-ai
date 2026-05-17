"""Pre/post anonymization middleware — M2-B3.

The gateway's substitution surface. Sits between Tier Derivation and
the Provider Adapter (PRD §4.3) on the request path; wraps the
provider's streaming or non-streaming output on the response path.

Three callables form the public API:

* :func:`pre_anonymize_request` — request-path substitution. Mutates
  ``chat_request`` in place to replace entity text with pseudonyms.
  Returns the populated :class:`PseudonymMapper` so the response path
  can rehydrate, or ``None`` if any skip condition is met (the
  caller treats ``None`` as "skip the post-middleware too").
* :func:`post_anonymize_response` — response-path substitution for
  non-streaming responses. Walks each choice's message content and
  replaces pseudonyms with originals.
* :class:`StreamingRehydrator` — incremental tail-buffer rehydrator
  for streaming responses. Solves Decision B (pseudonyms can straddle
  SSE chunk boundaries): we hold an unresolved tail until a complete
  pseudonym crystallizes or the chunk ends.

Skip semantics (any one short-circuits to no-op):

1. ``config.enabled is False`` — master switch.
2. ``routed_tier not in config.apply_at_tiers`` — Tier 1 (local)
   doesn't benefit, and operators can configure which tiers do.
3. ``chat_request.lq_ai_privileged is True`` — Decision A; privileged
   chats are not substituted because rewriting privileged work
   product risks corrupting it.
4. ``chat_request.anonymize is False`` — per-request opt-out.

The conditions are checked top-down; the first hit wins. The mapper
is allocated only when all four conditions pass — when allocation
fails we never persist anything, so a skipped request leaves the
audit log clean.
"""

from __future__ import annotations

import re
from typing import Any

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.config import AnonymizationConfig
from app.providers.openai_schema import ChatCompletionRequest, ChatCompletionResponse

__all__ = [
    "StreamingRehydrator",
    "post_anonymize_response",
    "pre_anonymize_request",
]


# Semantic roles whose ``content`` is content the user (or model)
# generated. ``tool`` messages carry tool-call payloads and shouldn't
# be pseudonymized — those are structured outputs, not natural prose.
_ANONYMIZED_ROLES: frozenset[str] = frozenset({"user", "assistant", "system"})


def pre_anonymize_request(
    *,
    chat_request: ChatCompletionRequest,
    config: AnonymizationConfig,
    routed_tier: int,
    anonymizer: Anonymizer,
) -> PseudonymMapper | None:
    """Pseudonymize ``chat_request`` in place; return mapper or ``None``.

    Mutates ``chat_request.messages[*].content`` and the nested
    string values in ``chat_request.lq_ai_skill_inputs`` so the
    provider sees only pseudonyms. Returns the mapper carrying the
    ``pseudonym → original`` mapping so the post-middleware can
    rehydrate the response.

    ``None`` is the skip signal — the caller short-circuits the
    post-middleware on ``None`` so the response passes through
    unchanged.
    """

    if not config.enabled:
        return None
    if routed_tier not in config.apply_at_tiers:
        return None
    if chat_request.lq_ai_privileged:
        return None
    if not chat_request.anonymize:
        return None

    mapper = PseudonymMapper()

    for message in chat_request.messages:
        if message.role not in _ANONYMIZED_ROLES:
            continue
        if message.content is None:
            continue
        # M2-D2: per Decision M2-1, retrieved source documents stay
        # un-pseudonymized so the model sees intact source quotes for
        # citation grounding. The api/ marks the retrieval-context
        # system message with ``lq_ai_skip_anonymization=True``; the
        # middleware honors the flag here. Other system messages (the
        # chat's own system instructions, skill-assembled prompts)
        # still get pseudonymized normally.
        if getattr(message, "lq_ai_skip_anonymization", False):
            continue
        message.content = anonymizer.pseudonymize_into(message.content, mapper)

    if chat_request.lq_ai_skill_inputs:
        for skill_name, inputs in chat_request.lq_ai_skill_inputs.items():
            chat_request.lq_ai_skill_inputs[skill_name] = _pseudonymize_strings(
                inputs, anonymizer=anonymizer, mapper=mapper
            )

    return mapper


# Anchored to end of buffer: a sequence that starts with an uppercase
# letter, continues with uppercase letters or underscores, optionally
# followed by an underscore and (zero or more) digits, terminating at
# end-of-string. This matches every "could still grow into a pseudonym"
# tail state — from a lone uppercase letter to a fully formed token
# whose next character might be another digit.
#
# Examples of partial-at-end matches (held):
#   "P"            "PE"            "PERSON"            "PERSON_"
#   "PERSON_0"     "PERSON_0001"   (could grow to PERSON_00010)
#
# Examples of *non*-matches (emit cleanly):
#   "John"         (mixed case — not pseudonym-shaped)
#   "PERSON_0001 " (trailing whitespace crystallizes the token)
#   "hello!"       (no leading uppercase at tail)
_PARTIAL_PSEUDONYM_AT_END: re.Pattern[str] = re.compile(r"[A-Z][A-Z_]*(?:_\d*)?$")


class StreamingRehydrator:
    """Tail-buffer SSE rehydrator (Decision B (i)) — pseudonym-aware.

    Hands chunks of (provider-produced) text in via :meth:`process`;
    emits the same text with pseudonyms substituted by their
    originals. Holds at most a small tail (bounded by the longest
    in-flight pseudonym, typically <30 chars) when the buffer ends in
    a pattern that could still grow into a real pseudonym. Call
    :meth:`flush` at end-of-stream to drain whatever's in the tail.

    Invariants:

    * **No partial pseudonyms ever emit.** A caller seeing the output
      can rely on every byte being either a non-pseudonym character
      or part of a fully rehydrated original.
    * **Bounded buffering.** The buffer never holds more than one
      partial-pseudonym pattern at a time — when a chunk completes
      the pattern (or proves it wasn't one), the held tail flushes.
      Latency is bounded by the pseudonym length, not the stream
      length.
    * **Empty mapper is a no-op.** :meth:`Anonymizer.rehydrate`
      returns its input unchanged when the mapper has no
      assignments, so streams that never produced entities cost only
      the regex scan.
    """

    __slots__ = ("_anonymizer", "_buffer", "_mapper")

    def __init__(self, *, mapper: PseudonymMapper, anonymizer: Anonymizer) -> None:
        self._mapper = mapper
        self._anonymizer = anonymizer
        self._buffer: str = ""

    def process(self, chunk: str) -> str:
        """Absorb ``chunk``; return any text safe to emit (rehydrated)."""

        if not chunk:
            return ""
        self._buffer += chunk

        match = _PARTIAL_PSEUDONYM_AT_END.search(self._buffer)
        if match is None:
            # Nothing in the tail looks like an in-flight pseudonym;
            # safe to emit everything we've buffered.
            emit_raw = self._buffer
            self._buffer = ""
        else:
            # Hold from the start of the trailing partial pseudonym.
            emit_raw = self._buffer[: match.start()]
            self._buffer = self._buffer[match.start() :]

        if not emit_raw:
            return ""
        return self._anonymizer.rehydrate(emit_raw, self._mapper)

    def flush(self) -> str:
        """Emit whatever's in the tail, rehydrated. Clears the buffer."""

        if not self._buffer:
            return ""
        out = self._anonymizer.rehydrate(self._buffer, self._mapper)
        self._buffer = ""
        return out


def post_anonymize_response(
    *,
    response: ChatCompletionResponse,
    mapper: PseudonymMapper,
    anonymizer: Anonymizer,
) -> None:
    """Rehydrate each choice's message content in place.

    Walks ``response.choices`` and replaces pseudonyms in each
    ``message.content`` string with the originals from ``mapper``.
    Choices whose content is ``None`` (tool-call shaped responses)
    are left alone. Non-content fields (role, finish_reason, usage,
    routing metadata) are untouched.

    Per Decision D: the gateway rehydrates response *content* only.
    Citation rehydration happens downstream in the api/'s citation
    extraction, which operates on the already-rehydrated content.
    """

    for choice in response.choices:
        if choice.message.content is None:
            continue
        choice.message.content = anonymizer.rehydrate(choice.message.content, mapper)


def _pseudonymize_strings(value: Any, *, anonymizer: Anonymizer, mapper: PseudonymMapper) -> Any:
    """Recursively pseudonymize string leaves; pass other types through.

    Skill-input values are arbitrary JSON-shaped (dict/list/str/int/
    bool/None). Only ``str`` leaves carry natural-language content
    worth pseudonymizing; numbers and booleans aren't entities the
    analyzer recognizes anyway and round-tripping them through the
    analyzer would just waste cycles.
    """

    if isinstance(value, str):
        return anonymizer.pseudonymize_into(value, mapper)
    if isinstance(value, dict):
        return {
            k: _pseudonymize_strings(v, anonymizer=anonymizer, mapper=mapper)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_pseudonymize_strings(v, anonymizer=anonymizer, mapper=mapper) for v in value]
    return value
