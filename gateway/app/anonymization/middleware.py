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
  replaces pseudonyms with originals. On the caller's opt-in it also
  restores the pseudonyms in each tool call's arguments.
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

import json
import re
from typing import Any

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.config import AnonymizationConfig
from app.observability_helpers import get_tracer, record_attributes, traced
from app.providers.openai_schema import ChatCompletionRequest, ChatCompletionResponse

__all__ = [
    "StreamingRehydrator",
    "post_anonymize_response",
    "pre_anonymize_request",
]


# Semantic roles whose ``content`` is prose to pseudonymize as it stands.
# A ``tool`` message is walked too, but through :func:`_pseudonymize_document`:
# its content is a JSON document (a document read, a search result) whose
# string values are the prose, and the detector is given those, not the
# escapes and keys around them.
_ANONYMIZED_ROLES: frozenset[str] = frozenset({"user", "assistant", "system"})


def pre_anonymize_request(
    *,
    chat_request: ChatCompletionRequest,
    config: AnonymizationConfig,
    routed_tier: int,
    anonymizer: Anonymizer,
) -> PseudonymMapper | None:
    """Pseudonymize ``chat_request`` in place; return mapper or ``None``.

    Mutates ``chat_request.messages[*].content`` (every role, a ``tool``
    message's JSON string values included), the arguments of the tool calls
    an assistant message carries, and the nested string values in
    ``chat_request.lq_ai_skill_inputs`` so the provider sees only
    pseudonyms. What leaves the gateway for a provider is rewritten under
    one rule: a message's own ``lq_ai_skip_anonymization`` flag is the only
    exception. Returns the mapper carrying the
    ``pseudonym → original`` mapping so the post-middleware can
    rehydrate the response.

    ``None`` is the skip signal — the caller short-circuits the
    post-middleware on ``None`` so the response passes through
    unchanged.
    """

    tracer = get_tracer()
    with tracer.start_as_current_span("anonymization.pre") as span:
        record_attributes(
            span,
            **{"anonymization.enabled": config.enabled, "anonymization.tier": routed_tier},
        )

        skip_reason: str | None = None
        if not config.enabled:
            skip_reason = "disabled"
        elif routed_tier not in config.apply_at_tiers:
            skip_reason = "tier_floor"
        elif chat_request.lq_ai_privileged:
            skip_reason = "privileged"
        elif not chat_request.anonymize:
            skip_reason = "request_opt_out"

        if skip_reason is not None:
            record_attributes(
                span,
                **{
                    "anonymization.skip_reason": skip_reason,
                    "anonymization.entity_count": 0,
                },
            )
            span.add_event(f"anonymization.skip.{skip_reason}")
            return None

        mapper = PseudonymMapper()

        for message in chat_request.messages:
            # M2-D2: per Decision M2-1, retrieved source documents stay
            # un-pseudonymized so the model sees intact source quotes for
            # citation grounding. The api/ marks the retrieval-context
            # system message with ``lq_ai_skip_anonymization=True``; the
            # middleware honors the flag here. Other system messages (the
            # chat's own system instructions, skill-assembled prompts)
            # still get pseudonymized normally.
            if getattr(message, "lq_ai_skip_anonymization", False):
                continue
            if message.content is not None:
                if message.role in _ANONYMIZED_ROLES:
                    message.content = anonymizer.pseudonymize_into(message.content, mapper)
                elif message.role == "tool":
                    # A tool result is what a tool read: a document's text, a
                    # search's passages. It leaves the gateway like any other
                    # content, so it is pseudonymized like it. Between the
                    # backend's agents it stays as stored; this is the boundary.
                    message.content = _pseudonymize_document(
                        message.content, anonymizer=anonymizer, mapper=mapper
                    )
            if message.role == "assistant" and message.tool_calls:
                # The arguments of a call the model made on an earlier turn,
                # sent back with the conversation. A caller that asked for them
                # to be restored holds the originals; they must not leave as
                # such.
                for call in message.tool_calls:
                    function = call.get("function") if isinstance(call, dict) else None
                    if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                        function["arguments"] = _pseudonymize_document(
                            function["arguments"], anonymizer=anonymizer, mapper=mapper
                        )

        if chat_request.lq_ai_skill_inputs:
            for skill_name, inputs in chat_request.lq_ai_skill_inputs.items():
                chat_request.lq_ai_skill_inputs[skill_name] = _pseudonymize_strings(
                    inputs, anonymizer=anonymizer, mapper=mapper
                )

        counts = mapper.entity_counts()
        record_attributes(
            span,
            **{
                "anonymization.entity_count": sum(counts.values()),
                "anonymization.entity_types": sorted(counts.keys()),
            },
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


@traced("anonymization.post")
def post_anonymize_response(
    *,
    response: ChatCompletionResponse,
    mapper: PseudonymMapper,
    anonymizer: Anonymizer,
    restore_tool_arguments: bool = False,
) -> None:
    """Rehydrate each choice's message content in place.

    Walks ``response.choices`` and replaces pseudonyms in each
    ``message.content`` string with the originals from ``mapper``.
    Choices whose content is ``None`` (tool-call shaped responses)
    are left alone. Non-content fields (role, finish_reason, usage,
    routing metadata) are untouched.

    Per Decision D: by default the gateway rehydrates response *content* only.
    Citation rehydration happens downstream in the api/'s citation
    extraction, which operates on the already-rehydrated content.

    ``restore_tool_arguments`` is the caller's opt-in
    (``ChatCompletionRequest.lq_ai_restore_tool_arguments``). When it is
    set, the pseudonyms in each tool call's arguments are restored as
    well; see :func:`_restore_arguments`. Without it a tool call's
    arguments are returned as the model wrote them, as before. Restored
    arguments may be kept and sent back on a later turn: the request path
    pseudonymizes the arguments of an earlier call again
    (:func:`pre_anonymize_request`), so the originals do not leave.
    """

    originals = mapper.reverse() if restore_tool_arguments else {}
    for choice in response.choices:
        if choice.message.content is not None:
            choice.message.content = anonymizer.rehydrate(choice.message.content, mapper)
        if not originals or not choice.message.tool_calls:
            continue
        for call in choice.message.tool_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                function["arguments"] = _restore_arguments(arguments, originals)


# One call's arguments, in characters, above which nothing is restored. The
# backend bounds a call's arguments at 49,152 bytes; this is the gateway's own
# limit and does not depend on that one.
_MAX_RESTORED_ARGUMENT_CHARS = 65_536
# How deep the restored value may nest. A plan is three levels.
_MAX_RESTORED_ARGUMENT_DEPTH = 16


class _NotRestorable(ValueError):
    """The arguments are not a value this path will rewrite; return them as sent."""


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Refuse an object that names a member twice.

    Parsing would keep the last and drop the others, so writing the value back
    would repair it. The caller reads these arguments with a strict parser
    that refuses a duplicate; it must be given what the model wrote.
    """

    members: dict[str, Any] = {}
    for key, value in pairs:
        if key in members:
            raise _NotRestorable("duplicate member")
        members[key] = value
    return members


def _not_a_number(_: str) -> Any:
    raise _NotRestorable("NaN or Infinity is not JSON")


def _whole_pseudonyms(originals: dict[str, str]) -> re.Pattern[str]:
    """Match one of this request's pseudonyms where it stands as a whole token.

    A pseudonym inside a longer run of letters, digits or underscores is not
    one of ours as written: ``PERSON_00010`` is not ``PERSON_0001`` followed
    by a zero, and ``XPERSON_0001`` is not ``PERSON_0001``. Both are left as
    they are. Longest first, so that of two pseudonyms where one begins the
    other the longer is tried first.
    """

    names = sorted(originals, key=len, reverse=True)
    return re.compile(
        r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_])"
    )


def _restore_strings(
    value: Any, pattern: re.Pattern[str], originals: dict[str, str], depth: int = 0
) -> Any:
    """Restore pseudonyms in string values; leave member names and other types alone."""

    if depth > _MAX_RESTORED_ARGUMENT_DEPTH:
        raise _NotRestorable("nested too deeply")
    if isinstance(value, str):
        # One pass over the text as the model wrote it. What is put back is not
        # looked at again, so an original that happens to read like a pseudonym
        # is never replaced a second time.
        return pattern.sub(lambda match: originals[match.group(0)], value)
    if isinstance(value, dict):
        return {k: _restore_strings(v, pattern, originals, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore_strings(v, pattern, originals, depth + 1) for v in value]
    return value


def _restore_arguments(arguments: str, originals: dict[str, str]) -> str:
    """Restore pseudonyms in one tool call's JSON arguments, or return them as sent.

    ``originals`` is this request's own ``pseudonym -> original`` table. The
    arguments are a JSON document in a string. A pseudonym is replaced inside
    the parsed string values and the document is written out again: replacing
    inside the raw string would break it whenever an original holds a
    quotation mark or a backslash. Member names are not rewritten.

    Only a pseudonym this request assigned is restored, and only where it
    stands as a whole token (:func:`_whole_pseudonyms`). One the model altered
    or invented is left as it is; the caller decides what to do with it.

    The string is returned exactly as it was sent when it is not a JSON object
    or array, when an object names a member twice, when it holds ``NaN``,
    ``Infinity`` or a number too large to write back, when it holds a lone
    surrogate, when it is longer or more deeply nested than the bounds
    above, and when no value in it holds a pseudonym of this request. So a
    call with nothing to restore is never re-serialised, and a caller's strict
    parser sees what the model wrote.

    When something is restored the document is written with characters as
    themselves (no ``\\uXXXX`` escapes for non-ASCII text) and with members in
    the order they were sent. A number is written as Python writes it, which
    keeps its value and may not keep its spelling (``1.50`` becomes ``1.5``).

    This changes only what is returned to the gateway's caller. Nothing is
    sent to a provider from here.
    """

    if not originals or not arguments or len(arguments) > _MAX_RESTORED_ARGUMENT_CHARS:
        return arguments
    try:
        parsed = json.loads(
            arguments, object_pairs_hook=_unique_members, parse_constant=_not_a_number
        )
        if not isinstance(parsed, dict | list):
            return arguments
        restored = _restore_strings(parsed, _whole_pseudonyms(originals), originals)
        if restored == parsed:
            return arguments
        written = json.dumps(restored, ensure_ascii=False, allow_nan=False)
        # An escape such as ``\ud83d`` parses to a lone surrogate, which
        # cannot be written as UTF-8. Written as itself it would fail the whole
        # response when it is sent; sent as it arrived it is six plain
        # characters. So such arguments are returned as sent.
        written.encode("utf-8")
        return written
    except (ValueError, TypeError, RecursionError):
        # ``_NotRestorable`` and ``json.JSONDecodeError`` are both ``ValueError``.
        return arguments


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


def _pseudonymize_document(text: str, *, anonymizer: Anonymizer, mapper: PseudonymMapper) -> str:
    """Pseudonymize a JSON document held in a string, or the string as prose.

    A tool result and a tool call's arguments are JSON documents in a string.
    The detector is given each string value on its own, so that an escape (a
    backslash and an ``n`` for a line break) never stands against a name, and
    a member name or a number is never rewritten. Members keep their order.

    The string is returned exactly as it was when no value held an entity: a
    document with nothing to hide is never re-serialised. It is treated as
    prose, as a whole, when it is not a JSON object or array, when an object
    names a member twice (parsing would drop one and writing back would repair
    it), when it holds ``NaN`` or ``Infinity``, when it is nested too deeply,
    and when what would be written cannot be encoded. The fallback leaves
    the structure as it was and still replaces what the detector finds, so a
    document that cannot be walked is never sent as it stands.
    """

    try:
        parsed = json.loads(text, object_pairs_hook=_unique_members, parse_constant=_not_a_number)
        if not isinstance(parsed, dict | list):
            return anonymizer.pseudonymize_into(text, mapper)
        walked = _pseudonymize_strings(parsed, anonymizer=anonymizer, mapper=mapper)
        if walked == parsed:
            return text
        written = json.dumps(walked, ensure_ascii=False, allow_nan=False)
        written.encode("utf-8")
        return written
    except (ValueError, TypeError, RecursionError):
        # ``_NotRestorable`` and ``json.JSONDecodeError`` are both ``ValueError``,
        # as is the ``UnicodeEncodeError`` of a lone surrogate.
        return anonymizer.pseudonymize_into(text, mapper)
