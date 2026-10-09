"""Restoring pseudonyms in a tool call's arguments, on the caller's opt-in.

By default the response path restores a reply's text and returns a tool call's
arguments as the model wrote them (``test_middleware.py`` pins that). A caller
that reads the arguments itself and never sends them back to a model may ask
for them to be restored too (``lq_ai_restore_tool_arguments``; ADR 0038 D7, a
governed run's plan).

These tests cover the function alone: what is restored, and every case in
which the arguments must come back exactly as they were sent. The request
field and the provider payload are covered in
``test_inference_anonymization.py`` and ``test_openai_adapter.py``.
"""

from __future__ import annotations

import json

import pytest

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import post_anonymize_response
from app.providers.openai_schema import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionResponse,
    ChatCompletionUsage,
)


def _mapper(*originals: tuple[str, str]) -> PseudonymMapper:
    mapper = PseudonymMapper()
    for entity_type, original in originals:
        mapper.assign(entity_type, original)
    return mapper


def _call(arguments: object, *, name: str = "propose_plan", call_id: str = "call_1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def _response(calls: list | None, *, content: str | None = None) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-test",
        created=0,
        model="scripted-1",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content, tool_calls=calls),
                finish_reason="tool_calls",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _restored(arguments: object, mapper: PseudonymMapper, *, opt_in: bool = True) -> object:
    response = _response([_call(arguments)])
    post_anonymize_response(
        response=response,
        mapper=mapper,
        anonymizer=Anonymizer(),
        restore_tool_arguments=opt_in,
    )
    calls = response.choices[0].message.tool_calls
    assert calls is not None
    return calls[0]["function"]["arguments"]


JOHN = ("PERSON", "John Smith")  # PERSON_0001
ACME = ("ORGANIZATION", "Acme Ltd")  # ORGANIZATION_0001


@pytest.mark.unit
def test_a_plan_with_pseudonyms_comes_back_with_the_names() -> None:
    plan = {
        "tasks": [
            {
                "topic": "Notice given to PERSON_0001",
                "question": "Did ORGANIZATION_0001 give PERSON_0001 notice, and when?",
                "boundaries": "Only what the documents say about PERSON_0001.",
                "output_contract": "A short answer with quotations.",
                "stopping_condition": "Stop when the notice clause is found.",
            }
        ]
    }

    restored = _restored(json.dumps(plan), _mapper(JOHN, ACME))

    assert isinstance(restored, str)
    assert json.loads(restored) == {
        "tasks": [
            {
                "topic": "Notice given to John Smith",
                "question": "Did Acme Ltd give John Smith notice, and when?",
                "boundaries": "Only what the documents say about John Smith.",
                "output_contract": "A short answer with quotations.",
                "stopping_condition": "Stop when the notice clause is found.",
            }
        ]
    }
    # Members keep the order they were sent in.
    assert list(json.loads(restored)["tasks"][0]) == list(plan["tasks"][0])


@pytest.mark.unit
def test_without_the_opt_in_nothing_in_the_arguments_changes() -> None:
    arguments = '{"tasks": [{"topic": "PERSON_0001"}]}'

    assert _restored(arguments, _mapper(JOHN), opt_in=False) == arguments


@pytest.mark.unit
def test_an_original_with_a_quotation_mark_or_a_backslash_keeps_the_arguments_valid() -> None:
    # Replacing inside the raw string would end the JSON string early.
    mapper = _mapper(("PERSON", 'Dwayne "The Rock" Johnson'), ("LOCATION", "C:\\Deeds\\2024"))
    arguments = json.dumps({"tasks": [{"topic": "PERSON_0001 at LOCATION_0001"}]})

    restored = _restored(arguments, mapper)

    assert isinstance(restored, str)
    assert json.loads(restored) == {
        "tasks": [{"topic": 'Dwayne "The Rock" Johnson at C:\\Deeds\\2024'}]
    }


@pytest.mark.unit
def test_restored_arguments_are_written_with_characters_as_themselves() -> None:
    mapper = _mapper(("PERSON", "Zoë Müller"))
    arguments = json.dumps({"tasks": [{"topic": "Vertrag für PERSON_0001"}]}, ensure_ascii=False)

    restored = _restored(arguments, mapper)

    assert isinstance(restored, str)
    assert "Vertrag für Zoë Müller" in restored
    assert "\\u" not in restored


@pytest.mark.unit
def test_a_pseudonym_spelled_with_a_json_escape_is_restored() -> None:
    # ``\u005f`` is an underscore once the document is parsed.
    arguments = '{"tasks": [{"topic": "PERSON\\u005f0001 signed"}]}'

    restored = _restored(arguments, _mapper(JOHN))

    assert isinstance(restored, str)
    assert json.loads(restored) == {"tasks": [{"topic": "John Smith signed"}]}


@pytest.mark.unit
def test_member_names_are_not_rewritten() -> None:
    arguments = json.dumps({"PERSON_0001": "about PERSON_0001"})

    restored = _restored(arguments, _mapper(JOHN))

    assert isinstance(restored, str)
    assert json.loads(restored) == {"PERSON_0001": "about John Smith"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "written",
    [
        "Person_0001",  # the model changed the case
        "PERSON_1",  # and the digits
        "PERSON_00010",  # a longer token that begins with ours
        "XPERSON_0001",  # a longer token that ends with ours
        "PERSON_0001_A",
        "PERSON_0002",  # shaped like one, and never assigned in this request
        "ORGANIZATION_0001",
    ],
)
def test_a_pseudonym_the_model_altered_or_invented_is_left_as_it_is(written: str) -> None:
    arguments = json.dumps({"tasks": [{"topic": f"Notice to {written} today"}]})

    assert _restored(arguments, _mapper(JOHN)) == arguments


@pytest.mark.unit
def test_what_is_put_back_is_not_restored_a_second_time() -> None:
    # The first person's name happens to read like the second one's pseudonym.
    mapper = _mapper(("PERSON", "PERSON_0002"), ("PERSON", "Jane Roe"))
    arguments = json.dumps({"tasks": [{"topic": "PERSON_0001 and PERSON_0002"}]})

    restored = _restored(arguments, mapper)

    assert isinstance(restored, str)
    assert json.loads(restored) == {"tasks": [{"topic": "PERSON_0002 and Jane Roe"}]}


@pytest.mark.unit
def test_of_two_pseudonyms_where_one_begins_the_other_each_gets_its_own_original() -> None:
    mapper = PseudonymMapper()
    for index in range(1, 11):
        mapper.assign("PERSON", f"Person {index}")  # PERSON_0001 .. PERSON_0010
    arguments = json.dumps({"tasks": [{"topic": "PERSON_0001, PERSON_0010"}]})

    restored = _restored(arguments, mapper)

    assert isinstance(restored, str)
    assert json.loads(restored) == {"tasks": [{"topic": "Person 1, Person 10"}]}


@pytest.mark.unit
@pytest.mark.parametrize(
    "arguments",
    [
        # Not JSON: a caller's parser must see what the model wrote.
        'tasks: PERSON_0001 "unterminated',
        "",
        # JSON, but not an object or an array.
        '"PERSON_0001"',
        "42",
        "null",
        # An object that names a member twice. Parsing would drop one and
        # writing it back would repair what a strict caller refuses.
        '{"tasks": "PERSON_0001", "tasks": "PERSON_0001"}',
        '{"tasks": [{"topic": "PERSON_0001", "topic": "x"}]}',
        # Not JSON numbers.
        '{"tasks": "PERSON_0001", "n": NaN}',
        '{"tasks": "PERSON_0001", "n": Infinity}',
        '{"tasks": "PERSON_0001", "n": -Infinity}',
        # Nothing of ours in it: never re-serialised, spacing and escapes kept.
        '{ "tasks" : [ {"topic":"caf\\u00e9", "n": 1.50} ] }',
    ],
)
def test_arguments_this_path_will_not_rewrite_come_back_exactly_as_sent(arguments: str) -> None:
    assert _restored(arguments, _mapper(JOHN)) == arguments


@pytest.mark.unit
def test_arguments_past_the_size_or_depth_bound_come_back_exactly_as_sent() -> None:
    mapper = _mapper(JOHN)
    long = json.dumps({"tasks": "PERSON_0001", "pad": "x" * 70_000})
    assert _restored(long, mapper) == long

    deep: object = "PERSON_0001"
    for _ in range(40):
        deep = [deep]
    nested = json.dumps(deep)
    assert _restored(nested, mapper) == nested

    # Far past what the parser itself will follow.
    bottomless = "[" * 100_000 + "]" * 100_000
    assert _restored(bottomless, mapper) == bottomless


@pytest.mark.unit
def test_an_empty_mapping_changes_nothing() -> None:
    arguments = '{"tasks": [{"topic": "PERSON_0001"}]}'

    assert _restored(arguments, PseudonymMapper()) == arguments


@pytest.mark.unit
def test_arguments_that_are_not_a_string_are_left_alone() -> None:
    # An adapter that handed over a parsed object: not this path's to rewrite.
    arguments = {"tasks": [{"topic": "PERSON_0001"}]}

    assert _restored(arguments, _mapper(JOHN)) == {"tasks": [{"topic": "PERSON_0001"}]}


@pytest.mark.unit
def test_every_call_of_the_reply_is_restored_and_the_text_still_is() -> None:
    response = _response(
        [
            _call('{"a": "PERSON_0001"}', call_id="call_1"),
            # The schema admits any dictionary as a call; a malformed one is skipped.
            {"id": "call_2", "type": "function", "function": "not a function"},
            {"id": "call_3", "type": "function"},
            _call('{"b": "PERSON_0001"}', name="other", call_id="call_4"),
        ],
        content="PERSON_0001 is named in the plan.",
    )

    post_anonymize_response(
        response=response,
        mapper=_mapper(JOHN),
        anonymizer=Anonymizer(),
        restore_tool_arguments=True,
    )

    message = response.choices[0].message
    assert message.content == "John Smith is named in the plan."
    assert message.tool_calls is not None
    assert json.loads(message.tool_calls[0]["function"]["arguments"]) == {"a": "John Smith"}
    assert message.tool_calls[1]["function"] == "not a function"
    assert message.tool_calls[2] == {"id": "call_3", "type": "function"}
    assert json.loads(message.tool_calls[3]["function"]["arguments"]) == {"b": "John Smith"}
    # Names and identifiers are not text to restore.
    assert message.tool_calls[0]["function"]["name"] == "propose_plan"
    assert message.tool_calls[0]["id"] == "call_1"
