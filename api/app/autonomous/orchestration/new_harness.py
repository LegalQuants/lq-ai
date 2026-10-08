"""New harness: the run profile the chat composer offers as a model (ADR 0038 D1).

A request typed into a chat goes to an orchestrator. It does one of two things.
It proposes a plan of one to four tasks: the owner approves that exact plan, a
sub-agent works on each task, and the orchestrator combines their results into
the answer. Or, when the request needs nothing read or searched, it answers by
itself: that reply is delivered at once, with no plan and no approval, and is
labelled as read from nothing. The request is not limited to one kind of legal
work.

What makes it general:

* Both roles are instructed by the engine's own versioned prompt files, not by
  skills (D3). They are in ``prompts/new_harness/`` and are shown to the owner
  with each run.
* The planning call is shown the chat's recent messages and the date. It is
  offered one tool, ``propose_plan``, and hands its plan over as that call's
  arguments. A reply with no call is the orchestrator's own answer.
* In a matter, a task may search the knowledge bases attached to that matter
  when the request was accepted, by keyword. A file a search finds is numbered
  as a source, so a quotation from it is checked like a quotation from a
  selected document. No query embedding is requested: nothing new is sent to a
  model. A run outside a matter searches none.
* Documents are optional. The owner may select none to eight. With none, no
  task is offered the read tool and the answer is labelled unverified. With
  some, the delivered answer's quotations are checked against them by the
  Citation Engine's local stages; no judge model is called.
* The chat may be in a matter or in none. In a matter the matter's inference
  tier floor and privilege flag apply at every call. Outside a matter the run
  is never privileged, its floor is this profile's, and it reads only files
  that are filed in no matter (see ``reading``).
* Pseudonymization follows the operator's gateway setting for the routed tier.
  Each call's receipt records whether it was applied.

Granted to sub-agents: reading the selected documents, searching the matter's
knowledge bases, and the run's own working notes. Bundled helpers and
persistent skill workspaces are not granted
until the conditions in ADR 0035 D8c and D8d are met. Nothing here leaves the
deployment: no case-law, authority or MCP tool is granted.

It has its own operator switch and pinned route. Nothing is inherited from the
fictional profile.
"""

from typing import cast

from app.autonomous.orchestration.contracts import PhaseTools
from app.autonomous.orchestration.policy import ReasoningEffort
from app.autonomous.orchestration.profiles import (
    RouteSettings,
    RunLimits,
    RunProfile,
    register_profile,
)
from app.config import Settings

PROFILE = "new_harness_v1"
# Version 1 of each file had the plan written as a JSON object in the reply and
# knew no knowledge bases. Both stay beside these, so a run that pinned them
# can still show the text it ran on.
ROOT_PROMPT = "new_harness/orchestrator.v2"
CHILD_PROMPT = "new_harness/subagent.v2"


def _route(settings: Settings) -> RouteSettings:
    return RouteSettings(
        enabled=settings.new_harness_enabled,
        provider=settings.new_harness_provider,
        model=settings.new_harness_model,
        budget_usd=settings.new_harness_budget_usd,
        minimum_tier=settings.new_harness_minimum_tier,
        timeout_seconds=settings.new_harness_timeout_seconds,
        # An empty setting sends none and leaves the model's own default.
        reasoning_effort=cast(ReasoningEffort, settings.new_harness_reasoning_effort)
        if settings.new_harness_reasoning_effort
        else None,
    )


NEW_HARNESS_PROFILE = register_profile(
    RunProfile(
        id=PROFILE,
        title="New harness",
        summary=(
            "Answers a request that needs nothing read. Otherwise plans it as one to four "
            "tasks, runs the tasks you approve, and combines their results into one answer."
        ),
        reads=(
            "Your request, this chat's recent messages, the documents you select, if any, "
            "and in a matter the knowledge bases attached to it. "
            "No other files and no live sources."
        ),
        root_skill="",
        child_skill="",
        root_prompt=ROOT_PROMPT,
        child_prompt=CHILD_PROMPT,
        documents="optional",
        project_scope="any",
        child_tools=PhaseTools(
            analysis=("read_document", "read_note", "save_note", "search_knowledge_base")
        ),
        # A sub-agent re-sends what it has read on each turn, so the input
        # ceiling bounds how much of the selection one task can hold.
        limits=RunLimits(
            max_input_bytes=262_144,
            child_turn_limit=5,
            document_read_chars=40_000,
            deadline_seconds=7200,
            # A local model writes task answers of five to eight thousand
            # characters. One that runs past this is cut and marked, not lost.
            child_answer_chars=12_000,
        ),
        evidence="citations",
        route=_route,
        switch="LQ_AI_NEW_HARNESS_ENABLED",
        composer=True,
        reads_thread=True,
        pseudonymization="operator",
        planning="tool",
        planning_notice=(
            "Sending makes one model call within the displayed total cap. It receives your "
            "request, this chat's recent messages, and the names of the documents you selected "
            "and of the matter's knowledge bases. It either answers a request that needs nothing "
            "read, or proposes a plan. Nothing else runs until you approve the plan."
        ),
    )
)
