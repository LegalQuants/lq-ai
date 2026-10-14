"""What a prompt-pinned session's model calls open with (ADR 0038 D2, D3).

A session's system message is its pinned prompt file, whole and unchanged. The
user message that follows it is built here, from the run's own records and
nothing else. Two callers use these functions: the effect adapter, which sends
the message, and the owner's read of how a run was set up, which shows it. One
builder serves both, so what is shown is what was sent; the read also compares
the rebuilt request with the digest recorded when it went out.

The message carries facts in labelled sections: which step this is, the
request, the chat so far, the selected documents by number and name, the
knowledge bases a task may search by name, the date, the limits, and on the
combine step each task's result. It never carries a document's contents, and
it carries no instructions: those live in the prompt file, where a change is a
new version.

The limits stated are the run's own terms, frozen when its request was accepted
(:func:`app.autonomous.orchestration.profiles.run_terms`), and the engine holds
the run to the same numbers.

A planning call may also be offered one tool, ``propose_plan``, built here
(:func:`plan_tool`). It is how the orchestrator hands over its plan. It is not
in the run tool registry and no handler runs for it: the application reads the
call's arguments, and nothing is sent back to the model.

The section titles and the fences round each task's result are the assembler's
own lines. Text written by a person, a model or a document is placed between
them and cannot pass for one: the thread is quoted line by line, and anywhere
else a line that reads like a title or a fence is given the same quote mark
(:func:`_data`). What a run may do is enforced in code and never read back from
this text; the marking is so that the model is not shown a section or a result
that the application did not write.

Everything here is pure. Nothing reads the clock, the database or a setting.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    DocumentRef,
    KnowledgeBaseRef,
    PreparedPlan,
)
from app.autonomous.orchestration.inference import MAX_TOOL_CALLS
from app.autonomous.orchestration.planning import PlanningSnapshot, ThreadMessage
from app.autonomous.orchestration.profiles import RunProfile, run_terms
from app.autonomous.orchestration.tools import SEARCH_PASSAGES, SOURCES_PER_TASK
from app.errors import Forbidden

PLAN, TASK, COMBINE = "propose_plan", "work_on_task", "synthesize_answers"

# The titles this module writes, each on a line by itself.
_OWN_TITLES = (
    "STEP",
    "REQUEST",
    "CONVERSATION SO FAR",
    "DOCUMENTS",
    "KNOWLEDGE BASES",
    "TODAY'S DATE",
    "LIMITS",
    "TASK",
    "RESULTS",
)
_NOT_LETTERS = re.compile(r"[^A-Za-z ]+")


def _letters(line: str) -> str:
    """A line reduced to its letters and single spaces, case kept.

    Compatibility forms are folded first (NFKC), so a title spelled with fullwidth
    letters reads as the title. NFKC does not map look-alikes from other scripts, such
    as a Cyrillic capital O, so those still pass as ordinary text: the layout guard is
    for honesty, and nothing that is enforced reads it back.
    """
    return " ".join(_NOT_LETTERS.sub("", unicodedata.normalize("NFKC", line)).split())


# Compared by letters, so `## LIMITS`, `**LIMITS**`, `LIMITS:` and a title with an
# invisible character inside it all read as the title. Case is kept: the titles are
# capitals, and an ordinary heading such as `## Results` is not one of them.
_TITLES = frozenset(_letters(title) for title in _OWN_TITLES)
# A line fenced as `_result` fences a task: its opening line or its closing line.
_FENCE = re.compile(
    r"-{3,}\s*(?:task\s+\d+\s+of\s+\d+\b.*|end\s+of\s+task\s+\d+)\s*-{3,}", re.IGNORECASE
)
# Every character `str.splitlines` ends a line on.
_BREAKS = re.compile("[\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]+")


def _data(text: str) -> str:
    """Free text, with any line that could pass for the assembler's own marked as quoted.

    A section title on a line by itself, or a line fenced like a task's result,
    gets the quote mark the thread's lines carry. Every other line is kept byte
    for byte, line endings included, so ordinary text is returned unchanged.

    This keeps the layout honest. It is not what stops a run from doing something:
    tools, documents, limits and budgets are enforced in code and never read back
    from this text.
    """
    out = []
    for line in text.splitlines(keepends=True):
        bare = line.strip()
        quoted = bare.startswith(">")
        if not quoted and (_letters(bare) in _TITLES or _FENCE.search(bare)):
            out.append("> " + line.lstrip())
        else:
            out.append(line)
    return "".join(out)


def _one_line(text: str) -> str:
    """A name or a title, kept on the single line the assembler gives it."""
    return _BREAKS.sub(" ", text)


def _name(text: str, what: str) -> str:
    """A name on its one line, never readable as one of the assembler's titles.

    A name that is a title in all but punctuation (a file called ``LIMITS``)
    would make its line read as that title by the rule ``_data`` applies. Such
    a name is followed by what it is. Any other name is returned as it is.
    """
    line = _one_line(text)
    return f"{line} ({what})" if _letters(line) in _TITLES else line


def _documents(documents: Sequence[DocumentRef]) -> str:
    if not documents:
        return "None selected."
    return "\n".join(f"[{d.number}] {_name(d.filename, 'a file name')}" for d in documents)


def _knowledge_bases(knowledge_bases: Sequence[KnowledgeBaseRef]) -> str:
    return "\n".join(f"- {_name(k.name, 'a knowledge base name')}" for k in knowledge_bases)


def _thread(thread: Sequence[ThreadMessage]) -> str:
    """Earlier messages, each line marked as quoted so it cannot pass for a section."""
    if not thread:
        return "None. This request opens the chat."
    parts = []
    for message in thread:
        who = "User" if message.role == "user" else "Assistant"
        lines = [f"> {line}" if line else ">" for line in message.content.splitlines()]
        if message.cut:
            lines.append("> [This message was cut to fit.]")
        parts.append(f"{who}:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _date(snapshot: PlanningSnapshot | None) -> str:
    return f"{snapshot.today} (UTC)" if snapshot and snapshot.today else "Not recorded."


def _sections(*sections: tuple[str, str]) -> str:
    return "\n\n".join(f"{title}\n{body}" for title, body in sections)


def planning_message(profile: RunProfile, snapshot: PlanningSnapshot) -> str:
    """The plan step: the request, the chat so far, the documents by name.

    Where the plan is handed over by tool call the step is named Respond: the
    orchestrator may then answer by itself instead of proposing a plan.
    """
    terms = run_terms(profile, snapshot)
    by_tool = terms.planning == "tool"
    limits = [
        f"- Tasks: at most {snapshot.max_children}.",
        f"- Each task: at most {terms.task_turns} turns that use tools, then "
        f"an answer of at most {terms.task_answer_chars:,} characters.",
    ]
    if snapshot.documents:
        limits.append(f"- One read of a document returns at most {terms.read_chars:,} characters.")
    if snapshot.knowledge_bases:
        limits.append(
            f"- One search of the knowledge bases returns at most {SEARCH_PASSAGES} passages."
        )
    if by_tool:
        limits.append(
            f"- An answer you give yourself, without a plan: at most {terms.answer_chars:,} "
            "characters."
        )
    sections = [
        ("STEP", "Respond" if by_tool else "Plan"),
        ("REQUEST", _data(snapshot.goal)),
        ("CONVERSATION SO FAR", _thread(snapshot.thread)),
        ("DOCUMENTS", _documents(snapshot.documents)),
    ]
    if snapshot.knowledge_bases:
        # Present only when a task may search some, so a run with none opens
        # exactly as it did before knowledge bases could be searched.
        sections.append(("KNOWLEDGE BASES", _knowledge_bases(snapshot.knowledge_bases)))
    sections += [("TODAY'S DATE", _date(snapshot)), ("LIMITS", "\n".join(limits))]
    return _sections(*sections)


# The longest any field of one proposed task may be, as the tool's schema states
# it. Four tasks at this length fit the bound on one call's arguments.
PLAN_FIELD_CHARS = 2048


def plan_tool(max_tasks: int) -> dict[str, Any]:
    """The function schema of ``propose_plan``, the one tool a planning call is offered.

    Its arguments are the plan: the same object the strict proposal parser
    reads (``contracts.parse_research_proposal``). The schema tells the model
    the shape. The parser is what enforces it.
    """

    def text(limit: int, description: str) -> dict[str, Any]:
        return {"type": "string", "minLength": 1, "maxLength": limit, "description": description}

    task = {
        "type": "object",
        "additionalProperties": False,
        "required": ["topic", "question", "boundaries", "output_contract", "stopping_condition"],
        "properties": {
            "topic": text(256, "A short name for the task. The person sees it as its title."),
            "question": text(
                PLAN_FIELD_CHARS, "Exactly what the sub-agent must find out or produce."
            ),
            "boundaries": text(
                PLAN_FIELD_CHARS, "What the task must leave alone, and what it cannot cover."
            ),
            "output_contract": text(
                PLAN_FIELD_CHARS, "What the result must contain and how it is laid out."
            ),
            "stopping_condition": text(PLAN_FIELD_CHARS, "When the task is finished."),
        },
    }
    return {
        "type": "function",
        "function": {
            "name": PLAN,
            "description": (
                "Hand over your plan for this request as tasks for sub-agents. The person "
                "reads the plan and approves or rejects it before anything runs. Call this "
                "once, with every task in the one call. The arguments are one object with one "
                "member, tasks, and nothing else."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tasks"],
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": max_tasks,
                        "items": task,
                    }
                },
            },
        },
    }


def planning_tools(profile: RunProfile, snapshot: PlanningSnapshot) -> list[dict[str, Any]]:
    """What the planning call of this run is offered: ``propose_plan``, or nothing."""
    if not profile.prompted or run_terms(profile, snapshot).planning != "tool":
        return []
    return [plan_tool(snapshot.max_children)]


def task_message(
    profile: RunProfile,
    plan: PreparedPlan,
    snapshot: PlanningSnapshot | None,
    child: ChildAssignment,
) -> str:
    """One sub-agent's task, exactly as the approved plan states it."""
    task = child.task
    terms = run_terms(profile, snapshot)
    limits = [
        f"- Turns that may use tools: at most {child.turn_limit}.",
        f"- Tool calls in one turn: at most {MAX_TOOL_CALLS}.",
    ]
    if plan.documents:
        limits.append(f"- One read of a document returns at most {terms.read_chars:,} characters.")
    if plan.knowledge_bases:
        limits.append(
            f"- One search returns at most {SEARCH_PASSAGES} passages. You may cite at most "
            f"{SOURCES_PER_TASK} different knowledge-base files."
        )
    limits.append(f"- Your answer: at most {terms.task_answer_chars:,} characters.")
    sections = [
        (
            "TASK",
            "\n".join(
                (
                    f"Topic: {_one_line(task.topic)}",
                    f"Question: {_data(task.question)}",
                    f"Boundaries: {_data(task.boundaries)}",
                    f"The result must contain: {_data(task.output_contract)}",
                    f"Stop when: {_data(task.stopping_condition)}",
                )
            ),
        ),
        ("DOCUMENTS", _documents(plan.documents)),
    ]
    if plan.knowledge_bases:
        sections.append(("KNOWLEDGE BASES", _knowledge_bases(plan.knowledge_bases)))
    sections += [("TODAY'S DATE", _date(snapshot)), ("LIMITS", "\n".join(limits))]
    return _sections(*sections)


def _result(position: int, total: int, topic: dict[str, Any]) -> str:
    outcome = topic.get("outcome") or {}
    status = outcome.get("status")
    if status == "completed":
        state, body = "completed", "\n\n".join(str(f) for f in outcome.get("findings") or ())
    elif status == "empty":
        state, body = "found nothing", str(outcome.get("summary") or "")
    else:
        code = str(outcome.get("failure_code") or "no reason recorded").replace("_", " ")
        state, body = f"failed: {code}", str(outcome.get("summary") or "")
    return (
        f"--- Task {position} of {total}: {_one_line(str(topic.get('topic')))} ({state}) ---\n"
        f"{_data(body)}\n"
        f"--- End of task {position} ---"
    )


def combine_message(
    profile: RunProfile,
    plan: PreparedPlan,
    snapshot: PlanningSnapshot | None,
    topics: Sequence[dict[str, Any]],
) -> str:
    """The combine step: the request again, and what each task returned."""
    results = "\n\n".join(
        _result(position, len(topics), topic) for position, topic in enumerate(topics, 1)
    )
    return _sections(
        ("STEP", "Combine"),
        ("REQUEST", _data(plan.goal)),
        ("DOCUMENTS", _documents(plan.documents)),
        ("TODAY'S DATE", _date(snapshot)),
        ("RESULTS", results),
        (
            "LIMITS",
            f"- Your answer: at most {run_terms(profile, snapshot).answer_chars:,} characters.",
        ),
    )


def opening(
    profile: RunProfile,
    *,
    plan: PreparedPlan | PlanningSnapshot,
    snapshot: PlanningSnapshot | None,
    session_id: UUID,
    inputs: dict[str, Any],
) -> str:
    """The opening user message for one call of a prompt-pinned session.

    The task, the request, the thread and the documents are taken from the
    run's durable plan and intake. A caller supplies only which step it is and,
    for the combine step, the collected results. It cannot supply another
    session's task.
    """
    step = inputs.get("operation")
    if isinstance(plan, PlanningSnapshot):
        if step != PLAN or session_id != plan.root_id:
            raise Forbidden(message="Only the planning call is open before approval")
        return planning_message(profile, plan)
    if session_id == plan.root_id:
        topics = inputs.get("topics")
        if step != COMBINE or not isinstance(topics, list):
            raise Forbidden(message="An approved root only combines its tasks' results")
        return combine_message(profile, plan, snapshot, topics)
    child = next((c for c in plan.children if c.dispatch_id == session_id), None)
    if step != TASK or child is None:
        raise Forbidden(message="A sub-agent only works on its own approved task")
    return task_message(profile, plan, snapshot, child)
