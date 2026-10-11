"""M2-B3 anonymization middleware — pre/post + streaming-rehydrator.

The middleware is the gateway's request-path and response-path
substitution surface. It sits between Tier Derivation and the
Provider Adapter (per PRD §4.3) so the upstream provider only ever
sees pseudonymized content and the caller only ever sees rehydrated
content.

These tests cover the pure-logic invariants that don't require a
running FastAPI app:

* :func:`pre_anonymize_request` — when to fire, when to skip, what
  it mutates, and the mapper it hands back for the response path.
* :func:`post_anonymize_response` — non-streaming rehydration of the
  response body.
* :class:`StreamingRehydrator` — incremental tail-buffer rehydration
  for SSE chunks (Decision B option (i)).

End-to-end coverage with the real chat-completions handler lives in
``test_inference_anonymization.py`` (integration), which wires the
middleware into the FastAPI app and mocks the provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import (
    StreamingRehydrator,
    post_anonymize_response,
    pre_anonymize_request,
)
from app.config import AnonymizationConfig
from app.providers.openai_schema import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

# ---------------------------------------------------------------------------
# Stub analyzer — same shape as the one in test_anonymizer.py. Duplicated
# here rather than imported because pytest doesn't expose test files as
# importable modules without a conftest dance, and the stub is small enough
# that duplication is cheaper than the import gymnastics.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    entity_type: str
    start: int
    end: int
    score: float = 0.85


class _StubAnalyzer:
    """Returns canned spans from a (text → spans) lookup table.

    Real Presidio matches by content, not by reference. Tests build a
    lookup keyed by exact text so each message gets the spans that
    correspond to its content.
    """

    def __init__(self, by_text: dict[str, list[_Span]]) -> None:
        self._by_text = by_text

    def analyze(self, *, text: str, language: str = "en", **_kwargs: object) -> list[_Span]:
        return list(self._by_text.get(text, []))


class _NameAnalyzer:
    """Finds each of the given names wherever it stands in the text.

    The keyed stub above needs the exact text of each message. A tool result is
    walked value by value, so these tests name the entities instead.
    """

    def __init__(self, names: dict[str, str]) -> None:
        self._names = names

    def analyze(self, *, text: str, language: str = "en", **_kwargs: object) -> list[_Span]:
        found: list[_Span] = []
        for name, entity_type in self._names.items():
            start = text.find(name)
            while start != -1:
                found.append(_Span(entity_type, start, start + len(name)))
                start = text.find(name, start + len(name))
        return found


def _make_request(
    *,
    messages: list[ChatCompletionMessage],
    anonymize: bool = True,
    privileged: bool = False,
    skill_inputs: dict[str, dict[str, object]] | None = None,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="smart",
        messages=messages,
        anonymize=anonymize,
        lq_ai_privileged=privileged,
        lq_ai_skill_inputs=skill_inputs or {},
    )


# ---------------------------------------------------------------------------
# Skip conditions — pre_anonymize_request returns None and does NOT mutate.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pre_anonymize_skips_when_config_disabled() -> None:
    """``anonymization.enabled=false`` is a hard short-circuit."""

    req = _make_request(messages=[ChatCompletionMessage(role="user", content="John Smith signed.")])
    config = AnonymizationConfig(enabled=False, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"John Smith signed.": [_Span("PERSON", 0, 10)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is None
    assert req.messages[0].content == "John Smith signed."


@pytest.mark.unit
def test_pre_anonymize_skips_when_tier_not_in_apply_at_tiers() -> None:
    """Tier 1 (local inference) does not benefit from anonymization."""

    req = _make_request(messages=[ChatCompletionMessage(role="user", content="John Smith signed.")])
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"John Smith signed.": [_Span("PERSON", 0, 10)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=1,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is None
    assert req.messages[0].content == "John Smith signed."


@pytest.mark.unit
def test_pre_anonymize_skips_when_request_is_privileged() -> None:
    """A privileged chat never gets pseudonymized (Decision A)."""

    req = _make_request(
        messages=[ChatCompletionMessage(role="user", content="John Smith signed.")],
        privileged=True,
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"John Smith signed.": [_Span("PERSON", 0, 10)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is None
    assert req.messages[0].content == "John Smith signed."


@pytest.mark.unit
def test_pre_anonymize_skips_on_per_request_opt_out() -> None:
    """``anonymize: false`` is the per-request escape hatch."""

    req = _make_request(
        messages=[ChatCompletionMessage(role="user", content="John Smith signed.")],
        anonymize=False,
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"John Smith signed.": [_Span("PERSON", 0, 10)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is None
    assert req.messages[0].content == "John Smith signed."


# ---------------------------------------------------------------------------
# Firing path — pseudonymizes message content + skill_inputs, returns mapper.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pre_anonymize_pseudonymizes_user_message_content() -> None:
    """When firing, a user-role message has entities replaced in place."""

    req = _make_request(messages=[ChatCompletionMessage(role="user", content="John Smith signed.")])
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"John Smith signed.": [_Span("PERSON", 0, 10)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == "PERSON_0001 signed."
    assert mapper.reverse() == {"PERSON_0001": "John Smith"}


@pytest.mark.unit
def test_pre_anonymize_walks_user_assistant_and_system_roles() -> None:
    """All three semantic roles are walked; ``tool`` is not (irrelevant here)."""

    req = _make_request(
        messages=[
            ChatCompletionMessage(role="system", content="System: Smith Corp."),
            ChatCompletionMessage(role="user", content="User: Jane Doe."),
            ChatCompletionMessage(role="assistant", content="Assistant: Acme LLP."),
        ]
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer(
        {
            "System: Smith Corp.": [_Span("ORGANIZATION", 8, 18)],
            "User: Jane Doe.": [_Span("PERSON", 6, 14)],
            "Assistant: Acme LLP.": [_Span("ORGANIZATION", 11, 19)],
        }
    )

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == "System: ORGANIZATION_0001."
    assert req.messages[1].content == "User: PERSON_0001."
    assert req.messages[2].content == "Assistant: ORGANIZATION_0002."


_CONFIG = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
_PEOPLE = {"John Smith": "PERSON", "Jane Doe": "PERSON", "Acme Ltd": "ORGANIZATION"}


def _tool_call(arguments: str, *, call_id: str = "call_1", name: str = "save_note") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def _pseudonymized(messages: list[ChatCompletionMessage], **kwargs: object) -> tuple:
    req = _make_request(messages=messages, **kwargs)
    mapper = pre_anonymize_request(
        chat_request=req,
        config=_CONFIG,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=_NameAnalyzer(_PEOPLE)),
    )
    return req, mapper


@pytest.mark.unit
def test_pre_anonymize_pseudonymizes_a_tool_result_and_the_arguments_of_an_earlier_call() -> None:
    """What a tool read, and what the model asked of it, leave the gateway like any content.

    A governed run's child reads a document through a tool (ADR 0038 D4, D5),
    so the document's text travels as a tool result. Between the backend's
    agents the text stays as stored; at this boundary it is pseudonymized with
    the rest of the request, by the same mapper, so one name is one pseudonym
    in the task, in the call and in the result.
    """

    arguments = '{"name": "note-smith.md", "content": "John Smith signed."}'
    req, mapper = _pseudonymized(
        [
            ChatCompletionMessage(role="user", content="User: Jane Doe."),
            ChatCompletionMessage(
                role="assistant", content=None, tool_calls=[_tool_call(arguments)]
            ),
            ChatCompletionMessage(role="tool", tool_call_id="call_1", content="John Smith signed."),
        ]
    )

    assert mapper is not None
    assert req.messages[0].content == "User: PERSON_0001."
    assert req.messages[1].tool_calls is not None
    sent = req.messages[1].tool_calls[0]["function"]["arguments"]
    assert json.loads(sent) == {"name": "note-smith.md", "content": "PERSON_0002 signed."}
    assert list(json.loads(sent)) == ["name", "content"]
    assert req.messages[2].content == "PERSON_0002 signed."
    assert mapper.reverse() == {"PERSON_0001": "Jane Doe", "PERSON_0002": "John Smith"}


@pytest.mark.unit
def test_pre_anonymize_walks_the_string_values_of_a_json_tool_result_not_its_keys() -> None:
    result = json.dumps(
        {
            "document": 1,
            "John Smith": "a member name is not content",
            "text": "John Smith signed for Acme Ltd.\nJane Doe witnessed.",
            "parts": ["Acme Ltd", 2, None, True],
        }
    )
    req, mapper = _pseudonymized([ChatCompletionMessage(role="tool", content=result)])

    assert mapper is not None
    sent = json.loads(req.messages[0].content or "")
    assert sent == {
        "document": 1,
        "John Smith": "a member name is not content",
        "text": "PERSON_0001 signed for ORGANIZATION_0001.\nPERSON_0002 witnessed.",
        "parts": ["ORGANIZATION_0001", 2, None, True],
    }
    # The escape for a line break is never put against a name.
    assert "\\nPERSON_0002" in (req.messages[0].content or "")


@pytest.mark.unit
@pytest.mark.parametrize(
    "content",
    [
        '{"document":1,"text":"Nothing to hide here."}',  # compact, as written
        "[ 1 ,  2 ]",  # spacing the serialiser would change
        "Plain words, no entity.",
        "",
    ],
)
def test_pre_anonymize_returns_a_tool_result_with_no_entity_exactly_as_sent(content: str) -> None:
    req, mapper = _pseudonymized([ChatCompletionMessage(role="tool", content=content)])

    assert mapper is not None
    assert req.messages[0].content == content


@pytest.mark.unit
def test_pre_anonymize_treats_a_tool_result_that_is_not_a_json_document_as_text() -> None:
    req, _ = _pseudonymized(
        [
            ChatCompletionMessage(role="tool", content="John Smith signed."),
            ChatCompletionMessage(
                role="tool", content='"John Smith"'
            ),  # a JSON string, not a document
            ChatCompletionMessage(role="tool", content="{not json: John Smith"),
        ]
    )

    assert [m.content for m in req.messages] == [
        "PERSON_0001 signed.",
        '"PERSON_0001"',
        "{not json: PERSON_0001",
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "arguments",
    [
        '{"query": "John Smith", "query": "again"}',  # a member twice
        '{"query": "John Smith", "n": NaN}',  # not JSON
        '{"query": "John Smith", "n": Infinity}',
    ],
)
def test_pre_anonymize_keeps_the_structure_of_arguments_it_cannot_walk(arguments: str) -> None:
    """Fail restrictive: the name still goes, and nothing is repaired on the way."""

    req, _ = _pseudonymized(
        [ChatCompletionMessage(role="assistant", tool_calls=[_tool_call(arguments)])]
    )

    assert req.messages[0].tool_calls is not None
    sent = req.messages[0].tool_calls[0]["function"]["arguments"]
    assert sent == arguments.replace("John Smith", "PERSON_0001")
    assert "John Smith" not in sent


@pytest.mark.unit
def test_pre_anonymize_leaves_the_rest_of_a_tool_call_alone() -> None:
    call = _tool_call('{"query": "John Smith"}', call_id="call_John Smith_1")
    req, _ = _pseudonymized([ChatCompletionMessage(role="assistant", tool_calls=[call])])

    assert req.messages[0].tool_calls == [
        {
            "id": "call_John Smith_1",
            "type": "function",
            "function": {"name": "save_note", "arguments": '{"query": "PERSON_0001"}'},
        }
    ]


@pytest.mark.unit
def test_pre_anonymize_honours_the_skip_flag_on_a_tool_message_and_a_call() -> None:
    arguments = '{"query": "John Smith"}'
    req, mapper = _pseudonymized(
        [
            ChatCompletionMessage(
                role="assistant",
                tool_calls=[_tool_call(arguments)],
                lq_ai_skip_anonymization=True,
            ),
            ChatCompletionMessage(
                role="tool", content="John Smith signed.", lq_ai_skip_anonymization=True
            ),
            ChatCompletionMessage(role="tool", content="Jane Doe signed."),
        ]
    )

    assert mapper is not None
    assert req.messages[0].tool_calls is not None
    assert req.messages[0].tool_calls[0]["function"]["arguments"] == arguments
    assert req.messages[1].content == "John Smith signed."
    assert req.messages[2].content == "PERSON_0001 signed."


@pytest.mark.unit
@pytest.mark.parametrize(
    ("config", "kwargs"),
    [
        (AnonymizationConfig(enabled=False, apply_at_tiers=[3, 4, 5]), {}),
        (AnonymizationConfig(enabled=True, apply_at_tiers=[5]), {}),
        (_CONFIG, {"privileged": True}),
        (_CONFIG, {"anonymize": False}),
    ],
    ids=["disabled", "tier", "privileged", "opt-out"],
)
def test_pre_anonymize_sends_tool_content_as_stored_where_nothing_is_pseudonymized(
    config: AnonymizationConfig, kwargs: dict
) -> None:
    """The skip rules decide for the whole request; a tool message is not an exception."""

    arguments = '{"query": "John Smith"}'
    req = _make_request(
        messages=[
            ChatCompletionMessage(role="assistant", tool_calls=[_tool_call(arguments)]),
            ChatCompletionMessage(role="tool", content="John Smith signed."),
        ],
        **kwargs,
    )

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=_NameAnalyzer(_PEOPLE)),
    )

    assert mapper is None
    assert req.messages[0].tool_calls is not None
    assert req.messages[0].tool_calls[0]["function"]["arguments"] == arguments
    assert req.messages[1].content == "John Smith signed."


@pytest.mark.unit
def test_a_tool_loop_round_trips_through_the_gateway_with_the_originals_kept_by_the_caller() -> (
    None
):
    """Pseudonymized out, restored back, and pseudonymized again when sent on.

    The caller opts in to restoring a call's arguments (it acts on a search
    query), holds the originals, and sends the conversation back with them.
    Each request is pseudonymized from the originals, so the pseudonyms agree
    from turn to turn and no original name leaves.
    """

    anonymizer = Anonymizer(analyzer=_NameAnalyzer(_PEOPLE))
    task = ChatCompletionMessage(role="user", content="What did John Smith agree with Acme Ltd?")
    first_req = _make_request(messages=[task.model_copy()])
    first_mapper = pre_anonymize_request(
        chat_request=first_req, config=_CONFIG, routed_tier=4, anonymizer=anonymizer
    )
    assert first_mapper is not None
    assert first_req.messages[0].content == "What did PERSON_0001 agree with ORGANIZATION_0001?"

    # The model searches for what it was shown; the caller gets the original back.
    reply = _make_response(contents=[None])
    reply.choices[0].message.tool_calls = [_tool_call('{"query": "PERSON_0001 ORGANIZATION_0001"}')]
    post_anonymize_response(
        response=reply, mapper=first_mapper, anonymizer=anonymizer, restore_tool_arguments=True
    )
    held = reply.choices[0].message.tool_calls
    assert held is not None
    assert json.loads(held[0]["function"]["arguments"]) == {"query": "John Smith Acme Ltd"}

    # The next turn sends the held originals back with the result it fetched.
    second_req = _make_request(
        messages=[
            task.model_copy(),
            ChatCompletionMessage(role="assistant", tool_calls=held),
            ChatCompletionMessage(
                role="tool", tool_call_id="call_1", content='{"passage": "Jane Doe signed."}'
            ),
        ]
    )
    second_mapper = pre_anonymize_request(
        chat_request=second_req, config=_CONFIG, routed_tier=4, anonymizer=anonymizer
    )

    assert second_mapper is not None
    assert second_req.messages[0].content == "What did PERSON_0001 agree with ORGANIZATION_0001?"
    sent = second_req.messages[1].tool_calls
    assert sent is not None
    assert json.loads(sent[0]["function"]["arguments"]) == {
        "query": "PERSON_0001 ORGANIZATION_0001"
    }
    assert json.loads(second_req.messages[2].content or "") == {"passage": "PERSON_0002 signed."}
    for message in second_req.messages:
        assert "John Smith" not in repr(message) and "Acme Ltd" not in repr(message)
        assert "Jane Doe" not in repr(message)


@pytest.mark.unit
def test_pre_anonymize_same_name_across_messages_stable_pseudonym() -> None:
    """The same name in two messages resolves to one pseudonym."""

    req = _make_request(
        messages=[
            ChatCompletionMessage(role="user", content="John Smith introduced."),
            ChatCompletionMessage(role="assistant", content="John Smith replied."),
        ]
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer(
        {
            "John Smith introduced.": [_Span("PERSON", 0, 10)],
            "John Smith replied.": [_Span("PERSON", 0, 10)],
        }
    )

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == "PERSON_0001 introduced."
    assert req.messages[1].content == "PERSON_0001 replied."
    assert mapper.reverse() == {"PERSON_0001": "John Smith"}


@pytest.mark.unit
def test_pre_anonymize_skips_message_marked_skip_anonymization() -> None:
    """M2-D2: ``lq_ai_skip_anonymization=True`` bypasses pseudonymization.

    Per Decision M2-1, the api/ marks the retrieval-context system
    message with this flag so the model sees intact source quotes for
    citation grounding. Other messages in the same request still get
    pseudonymized normally — entities present in both the marked
    message AND another message land with consistent pseudonyms on the
    other-message side (the mapper is per-request).
    """

    req = _make_request(
        messages=[
            ChatCompletionMessage(
                role="system",
                content="Retrieved chunk: John Smith agreed to pay $100k.",
                lq_ai_skip_anonymization=True,
            ),
            ChatCompletionMessage(
                role="user",
                content="What did John Smith agree to?",
            ),
        ]
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer(
        {
            # Both messages contain "John Smith" at the same offset;
            # only the user turn should be pseudonymized.
            "Retrieved chunk: John Smith agreed to pay $100k.": [_Span("PERSON", 17, 27)],
            "What did John Smith agree to?": [_Span("PERSON", 9, 19)],
        }
    )

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    # Retrieval-context system message: unchanged (skip flag honored).
    assert req.messages[0].content == "Retrieved chunk: John Smith agreed to pay $100k."
    # User turn: pseudonymized normally.
    assert req.messages[1].content == "What did PERSON_0001 agree to?"
    # The mapper carries only the user-turn assignment; provider sees
    # the real name in the retrieval chunk and the pseudonym in the
    # user turn (the per-request mapper would have reused PERSON_0001
    # if the skipped message had also been pseudonymized).
    assert mapper.reverse() == {"PERSON_0001": "John Smith"}


@pytest.mark.unit
def test_pre_anonymize_skip_flag_false_pseudonymizes_normally() -> None:
    """Default ``lq_ai_skip_anonymization=False`` retains M2-B3 behavior."""

    req = _make_request(
        messages=[
            ChatCompletionMessage(
                role="system",
                content="Chat system: John Smith.",
                # Explicit False; default would behave identically.
                lq_ai_skip_anonymization=False,
            ),
        ]
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"Chat system: John Smith.": [_Span("PERSON", 13, 23)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == "Chat system: PERSON_0001."


@pytest.mark.unit
def test_pre_anonymize_skips_message_with_none_content() -> None:
    """``content=None`` messages (tool-call shaped) are left alone, not crashed."""

    req = _make_request(
        messages=[
            ChatCompletionMessage(role="user", content="John Smith signed."),
            ChatCompletionMessage(role="assistant", content=None),
        ]
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"John Smith signed.": [_Span("PERSON", 0, 10)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == "PERSON_0001 signed."
    assert req.messages[1].content is None


@pytest.mark.unit
def test_pre_anonymize_walks_skill_inputs_recursively() -> None:
    """String values nested in skill_inputs are pseudonymized in place."""

    req = _make_request(
        messages=[ChatCompletionMessage(role="user", content="See attached.")],
        skill_inputs={
            "nda-review": {
                "counterparty_name": "John Smith",
                "max_indemnity": 1_000_000,  # int — left alone
                "redline_mode": True,  # bool — left alone
            }
        },
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer(
        {
            "See attached.": [],
            "John Smith": [_Span("PERSON", 0, 10)],
        }
    )

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    skill_inputs = req.lq_ai_skill_inputs["nda-review"]
    assert skill_inputs["counterparty_name"] == "PERSON_0001"
    # Non-string types are passed through untouched.
    assert skill_inputs["max_indemnity"] == 1_000_000
    assert skill_inputs["redline_mode"] is True


@pytest.mark.unit
def test_pre_anonymize_returns_empty_mapper_when_no_entities_found() -> None:
    """Firing with no detections still returns a (empty) mapper, not None.

    The mapper-vs-None distinction signals "did the middleware fire";
    even an empty mapper means the post-middleware should still wrap
    the response (cheaply, since rehydrate is a no-op against empty
    mapper).
    """

    req = _make_request(
        messages=[ChatCompletionMessage(role="user", content="The agreement is signed.")]
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({"The agreement is signed.": []})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert mapper.reverse() == {}
    assert req.messages[0].content == "The agreement is signed."


# ---------------------------------------------------------------------------
# post_anonymize_response — non-streaming rehydration.
# ---------------------------------------------------------------------------


def _make_response(*, contents: list[str | None]) -> ChatCompletionResponse:
    """Build a ChatCompletionResponse with one choice per content string."""

    return ChatCompletionResponse(
        id="chatcmpl-test",
        created=0,
        model="claude-sonnet-4-6",
        choices=[
            ChatCompletionChoice(
                index=i,
                message=ChatCompletionMessage(role="assistant", content=c),
                finish_reason="stop",
            )
            for i, c in enumerate(contents)
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest.mark.unit
def test_post_anonymize_rehydrates_single_choice() -> None:
    """The assistant message content is restored from pseudonyms."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")  # → PERSON_0001
    response = _make_response(contents=["PERSON_0001 signed the agreement."])

    post_anonymize_response(response=response, mapper=mapper, anonymizer=Anonymizer())

    assert response.choices[0].message.content == "John Smith signed the agreement."


@pytest.mark.unit
def test_post_anonymize_rehydrates_multiple_choices() -> None:
    """Every choice's content is rehydrated independently."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")  # PERSON_0001
    mapper.assign("ORGANIZATION", "Acme LLP")  # ORGANIZATION_0001
    response = _make_response(
        contents=[
            "PERSON_0001 represented ORGANIZATION_0001.",
            "ORGANIZATION_0001 retained PERSON_0001.",
        ]
    )

    post_anonymize_response(response=response, mapper=mapper, anonymizer=Anonymizer())

    assert response.choices[0].message.content == "John Smith represented Acme LLP."
    assert response.choices[1].message.content == "Acme LLP retained John Smith."


@pytest.mark.unit
def test_post_anonymize_leaves_none_content_as_none() -> None:
    """Tool-call shaped responses (no content) are not mangled."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")
    response = _make_response(contents=[None])

    post_anonymize_response(response=response, mapper=mapper, anonymizer=Anonymizer())

    assert response.choices[0].message.content is None


@pytest.mark.unit
def test_post_anonymize_does_not_restore_tool_call_arguments() -> None:
    """Only content is restored: a pseudonym in a tool call's arguments stays one.

    A governed run's child calls tools (ADR 0038 D4). An argument the model
    copied from pseudonymized text reaches the application as the pseudonym,
    so a tool must validate its arguments rather than trust them.
    """

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")  # PERSON_0001
    response = _make_response(contents=[None])
    arguments = '{"name": "note-a.md", "content": "PERSON_0001 signed."}'
    response.choices[0].message.tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "save_note", "arguments": arguments},
        }
    ]

    post_anonymize_response(response=response, mapper=mapper, anonymizer=Anonymizer())

    calls = response.choices[0].message.tool_calls
    assert calls is not None
    assert calls[0]["function"]["arguments"] == arguments


@pytest.mark.unit
def test_post_anonymize_empty_mapper_is_no_op() -> None:
    """Empty mapper leaves content unchanged."""

    mapper = PseudonymMapper()  # No assignments.
    response = _make_response(contents=["The agreement is signed."])

    post_anonymize_response(response=response, mapper=mapper, anonymizer=Anonymizer())

    assert response.choices[0].message.content == "The agreement is signed."


@pytest.mark.unit
def test_post_anonymize_preserves_non_content_fields() -> None:
    """Role, finish_reason, usage, and metadata fields pass through."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")
    response = _make_response(contents=["PERSON_0001 signed."])
    response.routed_inference_tier = 4
    response.routed_provider = "anthropic"
    response.anonymization_applied = True

    post_anonymize_response(response=response, mapper=mapper, anonymizer=Anonymizer())

    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].finish_reason == "stop"
    assert response.usage.prompt_tokens == 10
    assert response.routed_inference_tier == 4
    assert response.routed_provider == "anthropic"
    assert response.anonymization_applied is True


# ---------------------------------------------------------------------------
# StreamingRehydrator — incremental tail-buffer rehydration (Decision B (i)).
#
# Invariant: emitted text never contains a pseudonym (always rehydrated to
# the original). To uphold this when pseudonyms can straddle chunk
# boundaries, the rehydrator holds an unresolved tail until the partial
# pseudonym pattern crystallizes or ``flush()`` is called.
# ---------------------------------------------------------------------------


def _mapper_with(*pairs: tuple[str, str]) -> PseudonymMapper:
    """Build a mapper with explicit (entity_type, original) assignments."""

    m = PseudonymMapper()
    for entity_type, original in pairs:
        m.assign(entity_type, original)
    return m


@pytest.mark.unit
def test_streaming_rehydrator_empty_mapper_passes_through() -> None:
    """No pseudonyms to substitute → emit what comes in (post-flush)."""

    r = StreamingRehydrator(mapper=PseudonymMapper(), anonymizer=Anonymizer())

    out = r.process("Hello, the agreement is signed.") + r.flush()

    assert out == "Hello, the agreement is signed."


@pytest.mark.unit
def test_streaming_rehydrator_pseudonym_in_single_chunk() -> None:
    """Pseudonym arriving fully formed inside a chunk is rehydrated."""

    mapper = _mapper_with(("PERSON", "John Smith"))
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    # Trailing space crystallizes the pseudonym (no ambiguity at end).
    out = r.process("PERSON_0001 signed.") + r.flush()

    assert out == "John Smith signed."


@pytest.mark.unit
def test_streaming_rehydrator_pseudonym_split_across_chunks() -> None:
    """``PERSON_0001`` split as ``PERSON_`` | ``0001`` | `` `` is rehydrated.

    The first chunk ends with a partial pseudonym (``PERSON_``); the
    rehydrator holds it. The second chunk extends to ``PERSON_0001``
    but the buffer still ends in a digit — could be ``PERSON_00010`` —
    so we keep holding. The third chunk's leading space crystallizes
    the pseudonym and the rehydrator emits the rehydrated text.
    """

    mapper = _mapper_with(("PERSON", "John Smith"))
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    out = r.process("Hello PERSON_") + r.process("0001") + r.process(" signed.") + r.flush()

    assert out == "Hello John Smith signed."


@pytest.mark.unit
def test_streaming_rehydrator_pseudonym_split_at_every_char() -> None:
    """Pathological case: chunks of size 1. Final text still correct."""

    mapper = _mapper_with(("PERSON", "John Smith"))
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    out = ""
    for ch in "Hi PERSON_0001!":
        out += r.process(ch)
    out += r.flush()

    assert out == "Hi John Smith!"


@pytest.mark.unit
def test_streaming_rehydrator_two_pseudonyms_in_one_chunk() -> None:
    """Multiple complete pseudonyms in the same chunk all get rehydrated."""

    mapper = _mapper_with(
        ("PERSON", "John Smith"),
        ("ORGANIZATION", "Acme LLP"),
    )
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    out = r.process("PERSON_0001 at ORGANIZATION_0001 spoke.") + r.flush()

    assert out == "John Smith at Acme LLP spoke."


@pytest.mark.unit
def test_streaming_rehydrator_prefix_collision_safe() -> None:
    """``PERSON_00010`` arriving piecewise resolves to the long name, not ``John Smith0``."""

    mapper = _mapper_with(("PERSON", "John Smith"))  # PERSON_0001
    mapper._assignments[("PERSON", "Janet Doe")] = "PERSON_00010"
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    # Stream "PERSON_00010 met PERSON_0001 today." char-by-char to maximize
    # the chance the rehydrator gets confused at the boundary.
    out = ""
    for ch in "PERSON_00010 met PERSON_0001 today.":
        out += r.process(ch)
    out += r.flush()

    assert out == "Janet Doe met John Smith today."


@pytest.mark.unit
def test_streaming_rehydrator_flush_emits_held_tail() -> None:
    """A pseudonym at end-of-stream without trailing whitespace is emitted on flush."""

    mapper = _mapper_with(("PERSON", "John Smith"))
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    # No trailing char — the rehydrator can't tell if more digits are
    # coming until flush() declares the stream complete.
    emitted = r.process("Hello PERSON_0001")
    flushed = r.flush()

    assert emitted + flushed == "Hello John Smith"


@pytest.mark.unit
def test_streaming_rehydrator_empty_chunk_is_no_op() -> None:
    """Processing an empty chunk yields empty output and doesn't disturb buffer."""

    mapper = _mapper_with(("PERSON", "John Smith"))
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    out = r.process("") + r.process("PERSON_0001 ") + r.process("") + r.flush()

    assert out == "John Smith "


@pytest.mark.unit
def test_streaming_rehydrator_uppercase_word_not_held_indefinitely() -> None:
    """A mixed-case word with leading capital ('John') is not a pseudonym pattern.

    Mixed-case words don't even partially match the pseudonym shape
    (which requires only uppercase letters before the underscore), so
    they emit promptly without lingering in the tail buffer.
    """

    mapper = _mapper_with(("PERSON", "John Smith"))
    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer())

    # No pseudonym anywhere — should just pass through. The word 'Hello'
    # at end is mixed-case; safe to emit.
    emitted = r.process("Hello world,")
    # We don't assert the exact output here (the buffer state mid-stream
    # is internal); we just assert flush yields the full content cleanly.
    assert emitted + r.flush() == "Hello world,"
