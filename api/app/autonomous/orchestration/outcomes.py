"""Bounded internal delivery for the demonstration; no implied verification."""

import json
import re
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.autonomous.orchestration.contracts import Snapshot, TaskText
from app.autonomous.orchestration.workspace import WorkspaceRef

# One finding of a task. Up to 0.8.0 a finding was at most 4,096 characters.
# A profile whose tasks are general returns its whole answer as one finding, so
# the bound is the largest answer a profile may allow (``RunLimits``). The run's
# working file that holds an outcome is bounded in bytes separately.
MAX_FINDING_CHARS = 16384
type Finding = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_FINDING_CHARS)
]


class TopicOutcome(Snapshot):
    status: Literal["completed", "empty", "failed"]
    summary: TaskText
    findings: Annotated[tuple[Finding, ...], Field(max_length=8)]
    verification: Literal["unverified"] = "unverified"
    failure_code: Literal["invalid_output", "execution_failed"] | None = None
    artifact: WorkspaceRef | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.status == "completed" and not self.findings:
            raise ValueError("completed topics require findings; use empty otherwise")
        if self.status != "completed" and self.findings:
            raise ValueError("empty or failed topics cannot claim findings")
        if (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("only failed topics carry a failure code")
        return self


class CollectedTopic(Snapshot):
    session_id: UUID
    topic: TaskText
    outcome: TopicOutcome


class DemonstrationResult(Snapshot):
    kind: Literal["orchestration_demonstration"] = "orchestration_demonstration"
    verification: Literal["unverified"] = "unverified"
    coverage: Literal["complete", "partial", "empty", "failed"]
    summary: Annotated[str, Field(min_length=1, max_length=16384)]
    topics: Annotated[tuple[CollectedTopic, ...], Field(min_length=1, max_length=4)]


class DirectAnswer(Snapshot):
    """A run's result when the orchestrator answered by itself (ADR 0038 D1).

    There was no plan, so there are no tasks and no approval. Nothing was read
    or searched for it: it rests on the request, the chat's recent messages and
    the model alone.
    """

    kind: Literal["orchestration_direct_answer"] = "orchestration_direct_answer"
    verification: Literal["unverified"] = "unverified"
    summary: Annotated[str, Field(min_length=1, max_length=16384)]


def cut_to_limit(text: str, limit: int, *, why: str | None = None) -> str:
    """Keep an answer up to its limit and say, in the answer, that it was cut.

    A model does not count characters well. An answer that runs past its limit
    is more use to the reader cut and marked than discarded; a quotation the
    cut falls inside loses its source marker and is then reported as unchecked.
    The result is never longer than ``limit``. ``why`` replaces the reason the
    note gives, for a cut that is not about the stated character limit.
    """
    if len(text) <= limit:
        return text
    reason = why or f"the text was longer than its limit of {limit:,} characters"
    note = f"\n\n[Cut here: {reason}.]"
    if limit <= len(note):
        # No room to say so. Not reachable with a shipped limit.
        return text[:limit]
    return text[: limit - len(note)].rstrip() + note


# Room for one finding inside a run working file of 65,536 bytes, with the
# outcome's other fields beside it.
_FINDING_BYTES = 60_000


def _control_character(char: str) -> bool:
    """C0 other than tab, line feed and carriage return; delete; and C1."""
    code = ord(char)
    return (code < 32 and char not in "\n\r\t") or 127 <= code <= 159


def general_outcome(content: str, finish_reason: str, *, limit: int = 4096) -> TopicOutcome:
    """Wrap a sub-agent's Markdown answer in a bounded, unverified result.

    For a profile whose tasks are not limited to one kind of work. The answer
    is taken as text whatever it looks like; it is never parsed as JSON. It is
    stored whole, as one finding, so nothing is split and rejoined on the way
    to the reader or to the call that combines the tasks' answers. An incomplete
    reply is refused, and no second model call is made to repair it.
    """
    answer = content.strip()
    if finish_reason != "stop" or not answer:
        raise ValueError("Incomplete answer")
    if any(_control_character(char) for char in answer):
        raise ValueError("Answer contains control characters")
    if not 1 <= limit <= MAX_FINDING_CHARS:
        raise ValueError("Answer limit exceeds what an outcome can hold")
    answer = cut_to_limit(answer, limit)
    while len(json.dumps(answer, ensure_ascii=False).encode("utf-8")) > _FINDING_BYTES:
        # The outcome is kept in one of the run's working files, which is
        # bounded in bytes. Text that is mostly multi-byte can reach that
        # bound before it reaches its character limit.
        answer = cut_to_limit(
            answer, len(answer) * 9 // 10, why="the text was too large to store whole"
        )
    summary = next(
        (
            line.strip()
            for line in answer.splitlines()
            if line.strip()
            and len(line.strip()) <= 512
            and not line.lstrip().startswith(("#", ">", "-", "*", "|", "`"))
        ),
        "The task returned an answer.",
    )
    return TopicOutcome(status="completed", summary=summary, findings=(answer,))


def topic_coverage(
    topics: tuple[CollectedTopic, ...],
) -> Literal["complete", "partial", "empty", "failed"]:
    statuses = {topic.outcome.status for topic in topics}
    if statuses == {"failed"}:
        return "failed"
    if "failed" in statuses:
        return "partial"
    if statuses == {"empty"}:
        return "empty"
    return "complete"


class PlanCarriesPlaceholders(ValueError):
    """The plan's arguments hold a gateway placeholder that later calls could not restore."""


# The gateway's placeholder for a value it pseudonymized: an entity type in
# capitals, an underscore and a four-digit counter, for example PERSON_0001.
#
# Looked for anywhere, also inside a longer run of characters (PERSON_0001s,
# XPERSON_0001, PERSON_00011). The gateway restores a plan's placeholders only
# where one stands as a whole token, and it restores a later reply's text by
# plain replacement, which would also hit one inside a longer run and put a
# name of that later request in its place. So whatever the gateway left in a
# plan, and a later replacement could hit, is refused here: nothing falls
# between the two rules.
_PLACEHOLDER = re.compile(r"[A-Z][A-Z_]{1,40}_[0-9]{4}")


def carries_placeholder(text: str) -> bool:
    """Whether text holds something shaped like a gateway placeholder.

    On a route that pseudonymizes, the gateway puts the real value back in a
    reply's text, not in a tool call's arguments. A plan handed over as a tool
    call keeps any placeholder it carries. The calls that follow have their
    own mappings: they cannot restore it, and may give the same placeholder to
    a different value. Such a plan is refused rather than run.

    The test is on shape, anywhere in the text, so text that only looks like
    a placeholder is refused too, and only where the planning call was in fact
    pseudonymized.
    """
    return _PLACEHOLDER.search(text) is not None


def arguments_carry_placeholder(arguments: str) -> bool:
    """Whether a tool call's arguments hold a placeholder, as written or once decoded.

    The arguments are a JSON string, and JSON can spell a character as an
    escape: ``PERSON\\u005f0002`` is ``PERSON_0002`` after parsing. The
    shape is therefore looked for in the string as it arrived and in every key
    and string value of the decoded arguments. Arguments that are not JSON are
    judged as written; they fail as a plan in any case.
    """
    if carries_placeholder(arguments):
        return True
    try:
        pending: list[object] = [json.loads(arguments)]
    except (ValueError, RecursionError):
        return False
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if carries_placeholder(value):
                return True
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return False


class PlanWrittenAsText(ValueError):
    """The reply is a plan written out as text, where the plan tool was to be called."""


# The name of the plan's one member as JSON writes it, at any depth of string
# encoding: "tasks", \"tasks\", \\\"tasks\\\" and so on.
_TASKS_MEMBER = re.compile(r'\\*"tasks\\*"')
_TASK_FIELDS = frozenset(
    {"topic", "question", "boundaries", "output_contract", "stopping_condition"}
)


def _written_plan(text: str) -> bool:
    """Whether a reply with no tool call is a plan, or a call, written as text.

    A model that misses its tool call writes the call out instead, in whatever
    form its provider's parser would have read. Recognised here:

    * a reply that names the plan tool and has a ``"tasks"`` member anywhere in
      it: the call wrapped in tags, in a provider's envelope, or as a function
      written out in text. The member may be inside arguments that are
      themselves a JSON string, where its quotation marks are escaped;
    * a reply that is, alone or inside one code fence, a JSON object with a
      ``tasks`` or ``tool_calls`` member or named ``propose_plan``, or a JSON
      list of objects that have the five fields of a task.

    Prose that mentions a plan is not one, and neither is prose that names the
    tool without writing a call.
    """
    if "propose_plan" in text and _TASKS_MEMBER.search(text):
        return True
    value = text
    if value.startswith("```") and value.endswith("```") and "\n" in value:
        value = value.split("\n", 1)[1][:-3]
    try:
        parsed = json.loads(value)
    except (ValueError, RecursionError):
        return False
    if isinstance(parsed, dict):
        return "tasks" in parsed or "tool_calls" in parsed or parsed.get("name") == "propose_plan"
    return (
        isinstance(parsed, list)
        and bool(parsed)
        and all(isinstance(item, dict) and set(item) >= _TASK_FIELDS for item in parsed)
    )


def direct_answer(content: object, finish_reason: object, *, limit: int) -> str:
    """The orchestrator's own reply to a request, bounded and ready to deliver.

    Where a plan is handed over by tool call, a complete reply with no call is
    the answer, or one question back to the person. It is taken as text and
    never parsed. Refused: an incomplete or empty reply; one with control
    characters; and a plan written out as text, which is neither an answer to
    show nor a plan that was handed over.
    """
    if not isinstance(content, str) or finish_reason != "stop":
        raise ValueError("Incomplete answer")
    answer = content.strip()
    if not answer or any(_control_character(char) for char in answer):
        raise ValueError("Answer is empty or contains control characters")
    if _written_plan(answer):
        raise PlanWrittenAsText("The plan was written as text")
    return cut_to_limit(answer, limit)
