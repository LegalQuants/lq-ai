"""The run tool registry: one governed definition per capability (ADR 0038 D3).

A tool is an input model, a handler, a cost quote, safety flags and a
plain-language label. Approved children take their tools from this registry
(D4). The chat tool loop and the matter-session planner are not moved here in
this increment; they move when they are next changed.

A registry entry grants nothing. A call runs only when the approved plan lists
the tool for the child's current phase, current operator policy still allows
it, the tool's intent is in the child's phase grants, and the store admits the
effect. Every handler reaches its capability through ``GuardedEffects`` and so
through ``guarded_tool_call``.

Destructive and confirmation-required tools cannot be registered for runs
(ADR 0015 D4): a child has no human at the keyboard to confirm with.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import DocumentRef
from app.errors import ValidationError
from app.schemas.autonomous import Phase

if TYPE_CHECKING:
    from app.autonomous.orchestration.effects import CostQuote, GuardedEffects
    from app.autonomous.orchestration.store import WorkerClaim

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
MAX_NOTES = 5

# Plain aliases, not ``type`` statements: the function schema offered to a model
# must be self-contained, and a named alias is emitted as a ``$defs`` reference.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
NoteName = Annotated[str, StringConstraints(pattern=r"^note-[a-z0-9-]{1,40}\.md$")]


class ToolInput(BaseModel):
    """Every run tool takes the model's stated reason for the call.

    The reason is recorded with the call in the run's own records. It is
    model-authored text, so it never enters an audit row (ADR 0016 P3).
    """

    # Lax coercion ("1" for 1) is harmless here; unknown fields are refused.
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: Reason = Field(description="One sentence: why this call is needed for the task.")


@dataclass(frozen=True)
class StepNote:
    """What the owner is shown for one step, kept with the step's receipt.

    ``tool`` and ``kind`` are registry names. ``reason`` is the model's own
    stated reason for a tool call. ``summarize`` reduces the result to counts,
    numbers and the owner's own file names; it must not return document text.
    The note is stored in the run's records and never in an audit row.
    """

    kind: str
    tool: str | None = None
    reason: str | None = None
    summarize: Callable[[Any], dict[str, Any]] | None = None

    def record(self, data: Any) -> dict[str, Any]:
        note: dict[str, Any] = {"kind": self.kind}
        if self.tool is not None:
            note["tool"] = self.tool
        if self.reason is not None:
            note["reason"] = self.reason[:512]
        if self.summarize is not None:
            note["summary"] = self.summarize(data)
        return note


@dataclass
class LoopState:
    """What one child's loop has learned so far. Rebuilt from receipts on replay."""

    documents: tuple[DocumentRef, ...]
    read_chars: int
    note_revisions: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    tool: RunTool
    effects: GuardedEffects
    claim: WorkerClaim
    effect_key: str
    phase: Phase
    args: ToolInput
    state: LoopState
    quote: CostQuote

    def note(self, summarize: Callable[[Any], dict[str, Any]]) -> StepNote:
        return StepNote(
            kind=self.tool.step_kind,
            tool=self.tool.name,
            reason=self.args.reason,
            summarize=summarize,
        )


@dataclass(frozen=True)
class ToolOutcome:
    """What the model is told about one call. ``ok`` is false for a refusal.

    ``code`` is set when a handler refused before reaching any capability, so
    no receipt exists yet; the loop then records the refusal under that code.
    """

    content: str
    ok: bool = True
    code: str | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class RunTool:
    name: str
    label: str
    description: str
    intent: ToolIntent
    input_model: type[ToolInput]
    handler: ToolHandler
    step_kind: str
    cost_usd: Decimal = Decimal("0")
    pricing_version: str = "local-run-tool-v1"
    destructive: bool = False
    requires_confirmation: bool = False

    def schema(self) -> dict[str, Any]:
        """The function schema offered to the model for this tool."""
        parameters = self.input_model.model_json_schema()
        parameters.pop("title", None)
        for prop in parameters.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


_TOOLS: dict[str, RunTool] = {}


def register_tool(tool: RunTool) -> RunTool:
    if (
        _NAME.fullmatch(tool.name) is None
        or _NAME.fullmatch(tool.step_kind) is None
        or not tool.label.strip()
    ):
        raise ValidationError(message="Run tool needs a bounded name and a plain-language label")
    if tool.destructive or tool.requires_confirmation:
        raise ValidationError(
            message="Destructive or confirmation-required tools cannot be granted to runs"
        )
    if tool.name in _TOOLS:
        raise ValidationError(message="Run tool is already registered")
    if not issubclass(tool.input_model, ToolInput):
        raise ValidationError(message="Run tool inputs must carry the stated reason")
    if not tool.cost_usd.is_finite() or tool.cost_usd < 0:
        raise ValidationError(message="Run tool needs a known nonnegative cost quote")
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> RunTool | None:
    return _TOOLS.get(name)


def registered_tools() -> tuple[RunTool, ...]:
    return tuple(_TOOLS[name] for name in sorted(_TOOLS))


@contextmanager
def temporary_tool(tool: RunTool) -> Iterator[RunTool]:
    """Register a tool for the duration of a block. Used by the contract test."""
    register_tool(tool)
    try:
        yield tool
    finally:
        _TOOLS.pop(tool.name, None)


def dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def refusal(code: str, message: str) -> str:
    """An error result the model can read. Never contains another party's data."""
    return dumps({"error": code, "message": message})


# --- Shipped tools -----------------------------------------------------------


class ReadDocumentInput(ToolInput):
    document: Annotated[int, Field(ge=1, le=128, description="The document's number.")]
    start: Annotated[
        int,
        Field(ge=0, le=50_000_000, description="Character offset to read from. Use 0 first."),
    ] = 0


async def _read_document(call: ToolCall) -> ToolOutcome:
    args = call.args
    assert isinstance(args, ReadDocumentInput)
    selected = next((d for d in call.state.documents if d.number == args.document), None)
    if selected is None:
        return ToolOutcome(
            refusal("document_not_selected", "That number is not in this run's selection."),
            ok=False,
            code="document_not_selected",
        )
    if call.state.read_chars < 256:
        return ToolOutcome(
            refusal(
                "input_limit",
                "This task has no room left to read more. Answer from what you have read.",
            ),
            ok=False,
            code="input_limit",
        )

    def facts(data: Any) -> dict[str, Any]:
        return {
            "document": selected.number,
            "filename": selected.filename,
            "start": int(data["offset"]),
            "end": int(data["end"]),
            "total_chars": int(data["total_chars"]),
            "truncated": bool(data["truncated"]),
        }

    result = await call.effects.read_document(
        call.claim,
        effect_key=call.effect_key,
        phase=call.phase,
        file_id=selected.file_id,
        offset=args.start,
        max_chars=min(call.state.read_chars, 65_536),
        step=call.note(facts),
        tool_quote=call.quote,
    )
    summary = facts(result.data)
    body: dict[str, Any] = {
        **summary,
        "source": f"[{selected.number}]",
        "text": result.data["text"],
    }
    if summary["truncated"]:
        body["note"] = (
            f"This read was cut at character {summary['end']} of {summary['total_chars']}. "
            f"Call again with start={summary['end']} to continue."
        )
    return ToolOutcome(dumps(body))


class SaveNoteInput(ToolInput):
    name: NoteName = Field(description="File name, for example note-payment.md.")
    content: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


def _file_facts(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or "error" in data:
        return {"error": str((data or {}).get("error", "refused"))}
    return {
        "name": str(data["name"]),
        "revision": int(data["revision"]),
        "size_bytes": int(data["size_bytes"]),
    }


async def _save_note(call: ToolCall) -> ToolOutcome:
    args = call.args
    assert isinstance(args, SaveNoteInput)
    revision = call.state.note_revisions.get(args.name, 0)
    if revision == 0 and len(call.state.note_revisions) >= MAX_NOTES:
        # The run's own notes and findings files share this session's storage.
        return ToolOutcome(
            refusal("storage_limit", f"This task may keep at most {MAX_NOTES} notes."),
            ok=False,
            code="storage_limit",
        )
    result = await call.effects.workspace(
        call.claim,
        effect_key=call.effect_key,
        phase=call.phase,
        intent=ToolIntent.workspace_write,
        params={"name": args.name, "revision": revision, "content": args.content},
        step=call.note(_file_facts),
        tool_quote=call.quote,
    )
    if result.outcome == "workspace_refused":
        return ToolOutcome(
            refusal(str(result.data.get("error", "refused")), "The note was not saved."), ok=False
        )
    call.state.note_revisions[args.name] = int(result.data["revision"])
    return ToolOutcome(dumps({"saved": _file_facts(result.data)}))


class ReadNoteInput(ToolInput):
    name: NoteName = Field(description="A note this task saved earlier.")


async def _read_note(call: ToolCall) -> ToolOutcome:
    args = call.args
    assert isinstance(args, ReadNoteInput)
    revision = call.state.note_revisions.get(args.name)
    if revision is None:
        return ToolOutcome(
            refusal("file_unavailable", "This task has not saved a note with that name."),
            ok=False,
            code="file_unavailable",
        )
    result = await call.effects.workspace(
        call.claim,
        effect_key=call.effect_key,
        phase=call.phase,
        intent=ToolIntent.workspace_read,
        params={"name": args.name, "revision": revision},
        step=call.note(_file_facts),
        tool_quote=call.quote,
    )
    if result.outcome == "workspace_refused":
        return ToolOutcome(
            refusal(str(result.data.get("error", "refused")), "The note could not be read."),
            ok=False,
        )
    return ToolOutcome(
        dumps({"name": args.name, "revision": revision, "content": result.data["content"]})
    )


READ_DOCUMENT = register_tool(
    RunTool(
        name="read_document",
        label="Read a selected document",
        description=(
            "Read the text of one document selected for this run, by its number. "
            "Long documents are returned in parts; the result says where it was cut."
        ),
        intent=ToolIntent.retrieve_chunks,
        input_model=ReadDocumentInput,
        handler=_read_document,
        step_kind="document_read",
        pricing_version="local-document-read-v1",
    )
)
SAVE_NOTE = register_tool(
    RunTool(
        name="save_note",
        label="Save a working note",
        description="Save a working note for this task. Notes are kept with the run.",
        intent=ToolIntent.workspace_write,
        input_model=SaveNoteInput,
        handler=_save_note,
        step_kind="note_saved",
        pricing_version="local-workspace-v1",
    )
)
READ_NOTE = register_tool(
    RunTool(
        name="read_note",
        label="Read back a working note",
        description="Read back a working note this task saved earlier.",
        intent=ToolIntent.workspace_read,
        input_model=ReadNoteInput,
        handler=_read_note,
        step_kind="note_read",
        pricing_version="local-workspace-v1",
    )
)
