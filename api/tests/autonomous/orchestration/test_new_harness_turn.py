"""New harness: the orchestrator's turn, and knowledge-base search (ADR 0038 D1, D5).

The planning call is offered one tool, ``propose_plan``. One call to it is the
plan, read from the call's arguments. A reply with no call is the
orchestrator's own answer: the run ends completed, with no plan and no
approval. Anything else fails the plan.

A task in a matter may search the knowledge bases attached to it by keyword.
A file a search finds is numbered as a source, and a quotation from it is
checked like a quotation from a selected document.

Real Postgres, store, guard, worker and checkpoint paths; only the provider is
controlled. A configured-provider acceptance run is a separate gate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from tests.autonomous.orchestration.model_harness import (
    CHATS,
    GOAL,
    approve,
    job,
    messages,
    new_chat,
    read,
    run_to_completion,
    sections,
    start_in_chat,
    tool_call,
)
from tests.autonomous.orchestration.test_document_runs import MSA, PROFILE, add_file
from tests.autonomous.orchestration.test_new_harness import (
    earlier,
    first_turn,
    plan_opening,
    requests_of,
    trace,
)

from app.autonomous.orchestration import assembly
from app.autonomous.orchestration.new_harness import NEW_HARNESS_PROFILE
from app.autonomous.orchestration.outcomes import carries_placeholder
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.profiles import run_terms
from app.autonomous.orchestration.tools import SOURCES_PER_TASK, source_block
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.chat import MessageCitation
from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.orchestration import (
    OrchestrationAdmission,
    OrchestrationPlan,
    OrchestrationRoot,
)
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase

pytestmark = pytest.mark.integration

THANKS = "You're welcome. Nothing was read or searched for this reply."
LEAVE = (
    "LEAVE POLICY\n\n"
    "2. Annual leave. Each employee is entitled to eighteen (18) days of annual leave "
    "in each calendar year.\n"
    "5. Carry forward. Unused annual leave may be carried forward for one year only.\n"
)
TRAVEL = (
    "TRAVEL POLICY\n\n"
    "3. Approval. Overseas travel requires written approval from a director at least "
    "fourteen (14) days before departure.\n"
)


@pytest.fixture
def harness(model_demo: SimpleNamespace) -> SimpleNamespace:
    """New harness on. A task answers at once unless a test gives it a script."""
    api = model_demo
    api.runtime.settings.new_harness_enabled = True
    api.gateway.child_script = [None]
    # No document is selected unless a test selects one.
    api.gateway.expected_documents = []
    api.gateway.child_answer = "From general knowledge only; no document was read."
    api.gateway.synthesis_answer = "## Answer\n\nFrom general knowledge only."
    return api


async def knowledge_base(
    api: SimpleNamespace,
    name: str,
    files: dict[str, str],
    *,
    attached: bool = True,
    file_project: UUID | None = None,
    owner_id: UUID | None = None,
) -> tuple[UUID, dict[str, str]]:
    """A knowledge base of ready text files, attached to the demo matter unless told not to be.

    Each file is one passage. ``file_project`` files it in a matter by upload.
    """
    owner = owner_id or api.env.owner_id
    ids: dict[str, str] = {}
    async with api.env.factory.begin() as db:
        kb = KnowledgeBase(owner_id=owner, name=name, hybrid_alpha=0.5)
        db.add(kb)
        await db.flush()
        for filename, text in files.items():
            file = File(
                owner_id=owner,
                project_id=file_project,
                filename=filename,
                mime_type="text/plain",
                size_bytes=len(text.encode()),
                hash_sha256="0" * 64,
                storage_path=str(uuid4()),
                ingestion_status="ready",
            )
            db.add(file)
            await db.flush()
            document = Document(
                file_id=file.id, parser="x", character_count=len(text), normalized_content=text
            )
            db.add(document)
            await db.flush()
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=0,
                    content=text,
                    page_start=1,
                    page_end=1,
                    char_offset_start=0,
                    char_offset_end=len(text),
                    tokens=None,
                    metadata_json={},
                )
            )
            db.add(KnowledgeBaseFile(kb_id=kb.id, file_id=file.id))
            ids[filename] = str(file.id)
        if attached:
            db.add(ProjectKnowledgeBase(project_id=api.env.project_id, knowledge_base_id=kb.id))
        return kb.id, ids


def search(query: str, call_id: str = "call_s") -> dict[str, Any]:
    return tool_call(
        "search_knowledge_base", {"query": query, "reason": "Find the passage."}, call_id
    )


async def audits(api: SimpleNamespace, root: str) -> list[str]:
    async with api.env.factory() as db:
        return list(
            await db.scalars(
                select(AuditLog.action)
                .where(AuditLog.resource_id == root)
                .order_by(AuditLog.timestamp, AuditLog.id)
            )
        )


# --- 1. The plan is one call to propose_plan ----------------------------------


async def test_the_plan_is_handed_over_as_one_tool_call(harness: SimpleNamespace) -> None:
    api = harness
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    # Frozen with the request: how the plan is handed over, and the run's limits.
    limits = NEW_HARNESS_PROFILE.limits
    assert value["planning"]["terms"] == {
        "task_turns": limits.child_turn_limit,
        "task_answer_chars": limits.child_answer_chars,
        "answer_chars": limits.combined_answer_chars,
        "read_chars": limits.document_read_chars,
        "planning": "tool",
    }
    assert await job(api, value["root_id"]) == "completed"

    # The call was offered the plan tool and nothing else, sized to the funded tasks.
    (sent,) = requests_of(api, "propose_plan")
    assert sent.tools == [assembly.plan_tool(value["planning"]["max_children"])]
    assert sections(plan_opening(api))["STEP"] == "Respond"
    planned = await read(api, value["root_id"])
    assert planned["status"] == "awaiting_approval" and planned["answered_directly"] is False
    assert [c["task"] for c in planned["tree"]["plan"]["children"]] == json.loads(
        api.gateway.proposal
    )["tasks"]
    # Planning stayed one model call: no tool result was sent back.
    assert len(requests_of(api, "propose_plan")) == 1

    final = await run_to_completion_from(api, planned)
    assert final["status"] == "completed" and final["answered_directly"] is False
    assert final["direct_answer"] is None and final["tree"]["result"]["summary"]


async def run_to_completion_from(api: SimpleNamespace, planned: dict[str, Any]) -> dict[str, Any]:
    root = planned["root_id"]
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    for child in planned["tree"]["plan"]["children"]:
        assert await job(api, root, child["dispatch_id"]) == "completed"
    assert await job(api, root) == "completed"
    return await read(api, root)


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        # Two calls, a call to another tool, and arguments that are not a plan.
        ("two", "invalid_proposal"),
        ("other", "invalid_proposal"),
        ("malformed", "invalid_proposal"),
        ("extra_field", "invalid_proposal"),
        # A plan written out as text was not handed over. It is not shown as an answer.
        ("as_text", "plan_not_handed_over"),
        ("as_fenced_text", "plan_not_handed_over"),
        ("call_as_text", "plan_not_handed_over"),
        # An empty reply is neither a plan nor an answer.
        ("empty", "invalid_proposal"),
    ],
)
async def test_a_reply_that_is_neither_one_plan_call_nor_an_answer_fails_the_plan(
    harness: SimpleNamespace, reply: str, reason: str
) -> None:
    api = harness
    proposal = api.gateway.proposal
    tasks = json.loads(proposal)["tasks"]
    api.gateway.plan_reply = {
        "two": (
            "",
            [tool_call("propose_plan", proposal, "a"), tool_call("propose_plan", proposal)],
        ),
        "other": ("", [tool_call("read_document", {"document": 1, "reason": "x"})]),
        "malformed": ("", [tool_call("propose_plan", '{"tasks": [')]),
        "extra_field": (
            "",
            [tool_call("propose_plan", {"tasks": [{**tasks[0], "tools": ["read_document"]}]})],
        ),
        "as_text": (proposal, None),
        "as_fenced_text": (f"```json\n{proposal}\n```", None),
        "call_as_text": (json.dumps({"name": "propose_plan", "arguments": {"tasks": tasks}}), None),
        "empty": ("   ", None),
    }[reply]
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    assert await job(api, value["root_id"]) == "completed"
    failed = await read(api, value["root_id"])
    assert (failed["status"], failed["stop_reason"]) == ("failed", reason)
    assert failed["tree"] is None and failed["answered_directly"] is False
    # Nothing was delivered and nothing can be approved.
    assert [m["content"] for m in await messages(api, chat_id)] == [GOAL, ""]
    async with api.env.factory() as db:
        assert not (await db.scalars(select(OrchestrationPlan.root_id))).all()


@pytest.mark.parametrize("pseudonymized", [True, False])
async def test_a_plan_that_carries_a_placeholder_is_refused_where_the_call_was_pseudonymized(
    harness: SimpleNamespace, pseudonymized: bool
) -> None:
    """The gateway puts a name back in a reply's text, not in a tool call's arguments.

    A plan handed over as a tool call would keep its placeholders, and no later
    call could restore them. Where the planning call was not pseudonymized, the
    same characters are only text.
    """
    api = harness
    if not pseudonymized:
        api.gateway.config["anonymization"] = {"enabled": True, "apply_at_tiers": []}
    task = {
        **json.loads(api.gateway.proposal)["tasks"][0],
        "question": "What notice must PERSON_0002 give to end the agreement early?",
    }
    api.gateway.plan_reply = ("", [tool_call("propose_plan", {"tasks": [task]})])
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    assert await job(api, value["root_id"]) == "completed"
    after = await read(api, value["root_id"])
    (planning,) = after["effects"]
    assert planning["accounting"]["anonymization_applied"] is pseudonymized
    if pseudonymized:
        assert (after["status"], after["stop_reason"]) == ("failed", "plan_has_placeholders")
        assert after["tree"] is None
        assert [m["content"] for m in await messages(api, chat_id)] == [GOAL, ""]
    else:
        assert after["status"] == "awaiting_approval"
        assert [c["task"] for c in after["tree"]["plan"]["children"]] == [task]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Ask PERSON_0001 about it.", True),
        ("EMAIL_ADDRESS_0012", True),
        ("(PHONE_NUMBER_0003)", True),
        ("PERSON_0001's notice", True),
        # Not the gateway's shape: three digits, five digits, lower case, no type.
        ("ISO_900", False),
        ("PERSON_00011", False),
        ("person_0001", False),
        ("_0001", False),
        ("XPERSON_0001X", False),
        ("Clause 12.1 and section 2024", False),
    ],
)
def test_what_counts_as_a_placeholder(text: str, found: bool) -> None:
    assert carries_placeholder(text) is found


async def test_a_plan_in_another_script_arrives_as_written(harness: SimpleNamespace) -> None:
    api = harness
    task = {
        "topic": "§ 4 — Frais et délais",
        "question": "Que doit payer le client, et quand ? 支払条件は何ですか。",
        "boundaries": "Seulement le contrat « cadre ».",
        "output_contract": "Une réponse fondée sur les clauses.",
        "stopping_condition": "Une réponse.",
    }
    # As a provider adapter passes it on: characters as themselves, not escaped.
    arguments = json.dumps({"tasks": [task]}, ensure_ascii=False)
    api.gateway.plan_reply = ("", [tool_call("propose_plan", arguments)])
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    assert await job(api, value["root_id"]) == "completed"
    planned = await read(api, value["root_id"])
    assert [c["task"] for c in planned["tree"]["plan"]["children"]] == [task]


# --- 2. A reply with no call is the orchestrator's own answer -----------------


async def test_the_orchestrator_may_answer_by_itself(harness: SimpleNamespace) -> None:
    api = harness
    api.gateway.direct_answer = THANKS
    chat_id = await new_chat(api)
    await earlier(api, chat_id, ("user", "What is an indemnity?"), ("assistant", "A promise."))
    value = await start_in_chat(api, chat_id, profile=PROFILE, goal="Thanks.")
    root = value["root_id"]
    assert await job(api, root) == "completed"

    done = await read(api, root)
    # Completed with no plan: nothing to approve, no tasks, and it says so.
    assert (done["status"], done["stop_reason"]) == ("completed", None)
    assert done["answered_directly"] is True and done["tree"] is None
    # The run read carries the answer, for the receipt page; a planned run's is in its tree.
    assert done["direct_answer"] == THANKS
    assert done["evidence"] == "unverified" and done["evidence_result"] is None
    assert [m["content"] for m in await messages(api, chat_id)][-2:] == ["Thanks.", THANKS]
    # One model call was made, and it is the whole of the run.
    assert [e["effect_key"] for e in done["effects"]] == ["chat:plan:v1"]
    assert len(api.gateway.requests) == 1 and not api.queued[1:]
    async with api.env.factory() as db:
        row = await db.get(OrchestrationRoot, UUID(root))
        session = await db.get(AutonomousSession, UUID(root))
        assert row is not None and session is not None
        assert (row.status, row.current_revision, row.admitted_revision) == (
            "completed",
            None,
            None,
        )
        assert (session.status, session.current_phase) == ("completed", "delivery")
        assert session.result == {
            "kind": "orchestration_direct_answer",
            "verification": "unverified",
            "summary": THANKS,
        }
        assert not (await db.scalars(select(OrchestrationPlan.root_id))).all()
        assert not (await db.scalars(select(OrchestrationAdmission.session_id))).all()
    recorded = await audits(api, root)
    assert recorded.count("orchestration.answered_directly") == 1
    assert "orchestration.root_delivered" not in recorded
    assert "orchestration.approved" not in recorded and "orchestration.plan_saved" not in recorded

    # The owner can read what was sent and what came back, as for any run.
    shown = await trace(api, root, root)
    (call,) = shown["calls"]
    assert (call["step"], call["sent"], call["check"]) == ("plan", True, "matches")
    assert [t["function"]["name"] for t in call["tools"]] == ["propose_plan"]
    (turn,) = shown["turns"]
    assert (turn["text"], turn["finish_reason"], turn["tool_calls"]) == (THANKS, "stop", [])

    # The run no longer holds the owner's one active-run allowance, and the next
    # request in the chat is shown this answer as part of the conversation.
    api.gateway.direct_answer = None
    following = await start_in_chat(api, chat_id, profile=PROFILE, goal="And a guarantee?")
    assert [(m["role"], m["content"]) for m in following["planning"]["thread"]][-2:] == [
        ("user", "Thanks."),
        ("assistant", THANKS),
    ]


async def test_a_direct_answer_is_cut_at_the_runs_limit_and_says_so(
    harness: SimpleNamespace,
) -> None:
    api = harness
    limit = NEW_HARNESS_PROFILE.limits.combined_answer_chars
    api.gateway.direct_answer = "word " * limit
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    assert await job(api, value["root_id"]) == "completed"
    answer = (await messages(api, chat_id))[-1]["content"]
    assert len(answer) <= limit and answer.endswith(f"limit of {limit:,} characters.]")


async def test_an_unfinished_reply_is_not_delivered_as_an_answer(harness: SimpleNamespace) -> None:
    api = harness
    api.gateway.direct_answer = "The answer begins but the model ran out of"
    api.gateway.plan_finish_reason = "length"
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    assert await job(api, value["root_id"]) == "completed"
    failed = await read(api, value["root_id"])
    assert (failed["status"], failed["stop_reason"]) == ("failed", "invalid_proposal")
    assert (await messages(api, chat_id))[-1]["content"] == ""


async def test_a_direct_answer_that_quotes_a_selected_document_is_checked(
    harness: SimpleNamespace,
) -> None:
    api = harness
    chat_id = await new_chat(api)
    msa = await add_file(api, "msa.txt", MSA)
    # The orchestrator read nothing. One quotation happens to be in the document
    # and one is made up; each is reported as it is found.
    api.gateway.direct_answer = (
        'Fees are due "within thirty (30) days of the invoice date" (Source: [1]), and '
        '"interest accrues at twelve percent per annum" (Source: [1]).'
    )
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[msa])
    assert await job(api, value["root_id"]) == "completed"
    done = await read(api, value["root_id"])
    assert done["answered_directly"] is True and done["evidence"] == "citations"
    result = done["evidence_result"]
    assert (result["checked"], result["matched"], result["unmatched"]) == (2, 1, 1)
    assert result["gate_status"] == "flagged"


async def test_the_fictional_profile_still_plans_in_text_and_cannot_answer_by_itself(
    model_demo: SimpleNamespace,
) -> None:
    api = model_demo
    api.gateway.proposal = THANKS
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id)
    assert value["planning"].get("terms") is None
    assert await job(api, value["root_id"]) == "completed"
    assert requests_of(api, "propose_plan")[0].tools is None
    failed = await read(api, value["root_id"])
    assert (failed["status"], failed["stop_reason"]) == ("failed", "invalid_proposal")
    assert failed["answered_directly"] is False


async def test_a_run_recorded_before_terms_reads_its_profile_and_plans_in_text(
    harness: SimpleNamespace,
) -> None:
    api = harness
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    stored = dict(value["planning"])
    stored.pop("terms")
    snapshot = PlanningSnapshot.model_validate_json(json.dumps(stored))
    terms = run_terms(NEW_HARNESS_PROFILE, snapshot)
    assert terms == NEW_HARNESS_PROFILE.terms().model_copy(update={"planning": "text"})
    # Its planning call is rebuilt as it was sent: the step named Plan, and no tool.
    assert sections(assembly.planning_message(NEW_HARNESS_PROFILE, snapshot))["STEP"] == "Plan"
    assert assembly.planning_tools(NEW_HARNESS_PROFILE, snapshot) == []
    # An intake without terms keeps the digest it had before the field existed.
    assert "terms" not in snapshot.model_dump(mode="json")


# --- 3. Knowledge-base search -------------------------------------------------


async def test_a_task_searches_the_matters_knowledge_bases_and_its_quotations_are_checked(
    harness: SimpleNamespace,
) -> None:
    api = harness
    kb_id, files = await knowledge_base(api, "People policies", {"leave.txt": LEAVE})
    _, other = await knowledge_base(api, "Travel", {"travel.txt": TRAVEL})
    await knowledge_base(api, "Not attached", {"secret.txt": LEAVE}, attached=False)
    chat_id = await new_chat(api)
    listed = (await api.client.get(f"{CHATS}/{chat_id}/run-documents")).json()
    assert [k["name"] for k in listed["knowledge_bases"]] == ["People policies", "Travel"]

    quote = '"eighteen (18) days of annual leave" (Source: [1])'
    api.gateway.child_script = [[search("annual leave")], None]
    api.gateway.child_answer = f"Each employee gets {quote}."
    api.gateway.synthesis_answer = f"## Leave\n\nThe entitlement is {quote}."
    api.gateway.proposal = json.dumps({"tasks": json.loads(api.gateway.proposal)["tasks"][:1]})
    value = await start_in_chat(api, chat_id, profile=PROFILE)
    # The intake names the knowledge bases, and the plan carries them to approval.
    assert [k["name"] for k in value["planning"]["knowledge_bases"]] == [
        "People policies",
        "Travel",
    ]
    assert await job(api, value["root_id"]) == "completed"
    opening = sections(plan_opening(api))
    assert opening["KNOWLEDGE BASES"] == "- People policies\n- Travel"
    planned = await read(api, value["root_id"])
    plan = planned["tree"]["plan"]
    assert [k["name"] for k in plan["knowledge_bases"]] == ["People policies", "Travel"]
    # No documents were selected, so the read tool is not offered; the search is.
    assert plan["children"][0]["tools"]["analysis"] == [
        "read_note",
        "save_note",
        "search_knowledge_base",
    ]

    final = await run_to_completion_from(api, planned)
    assert final["status"] == "completed"
    task = first_turn(api, plan["children"][0]["task"]["topic"])
    assert sections(task.messages[1].content)["KNOWLEDGE BASES"] == "- People policies\n- Travel"
    # What the model was shown: the passage, numbered, with its file and knowledge base.
    (result,) = [json.loads(r) for r in api.gateway.tool_results]
    assert result["results"] == [
        {
            "source": "[1]",
            "file": "leave.txt",
            "knowledge_base": "People policies",
            "page": 1,
            "text": LEAVE,
        }
    ]
    # The step says what was found by number and name, and holds no passage text.
    (step,) = [
        e["step"]
        for e in final["tree"]["children"][0]["effects"]
        if e["step"] and e["step"]["kind"] == "knowledge_search"
    ]
    assert step["tool"] == "search_knowledge_base" and step["reason"] == "Find the passage."
    assert step["summary"] == {
        "passages": 1,
        "sources": [
            {
                "number": 1,
                "file_id": files["leave.txt"],
                "document_id": step["summary"]["sources"][0]["document_id"],
                "filename": "leave.txt",
            }
        ],
        "listed": 2,
        "searched": 2,
        "failed": 0,
        "withheld": 0,
    }
    assert "eighteen" not in json.dumps(final["tree"]["children"][0]["effects"])
    assert [(s["number"], s["filename"], s["file_id"]) for s in final["sources"]] == [
        (1, "leave.txt", files["leave.txt"])
    ]
    # The quotation named a file a search found, and it was checked against that file.
    assert final["evidence"] == "citations"
    checked = final["evidence_result"]
    assert (checked["checked"], checked["matched"], checked["unmatched"]) == (1, 1, 0)
    async with api.env.factory() as db:
        (citation,) = (await db.scalars(select(MessageCitation))).all()
        assert str(citation.source_file_id) == files["leave.txt"] and citation.verified is True
    assert other and kb_id


async def test_each_task_numbers_its_sources_in_its_own_block(harness: SimpleNamespace) -> None:
    api = harness
    await knowledge_base(api, "Policies", {"leave.txt": LEAVE, "travel.txt": TRAVEL})
    chat_id = await new_chat(api)
    msa = await add_file(api, "msa.txt", MSA)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    api.gateway.child_script = [[search("annual leave", "a"), search("overseas travel", "b")], None]
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[msa])
    final = await run_to_completion(api, value)
    # One selected document, so the first task numbers from 2 and the second from 27.
    assert [source_block(1, position) for position in (1, 2)] == [1, 1 + SOURCES_PER_TASK]
    by_task: dict[str, list[tuple[int, str]]] = {}
    for source in final["sources"]:
        by_task.setdefault(source["session_id"], []).append((source["number"], source["filename"]))
    first, second = (c["dispatch_id"] for c in final["tree"]["plan"]["children"])
    assert by_task == {
        first: [(2, "leave.txt"), (3, "travel.txt")],
        second: [(27, "leave.txt"), (28, "travel.txt")],
    }


async def test_a_search_never_takes_a_file_out_of_another_matter(harness: SimpleNamespace) -> None:
    api = harness
    async with api.env.factory.begin() as db:
        elsewhere = Project(
            owner_id=api.env.owner_id, name="Elsewhere", slug=f"e-{uuid4().hex[:8]}"
        )
        db.add(elsewhere)
        await db.flush()
        other_matter = elsewhere.id
    await knowledge_base(api, "Mixed", {"leave.txt": LEAVE})
    await knowledge_base(api, "Held", {"held.txt": LEAVE}, file_project=other_matter)
    api.gateway.child_script = [[search("annual leave")], None]
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    final = await run_to_completion(api, value)
    results = [json.loads(r) for r in api.gateway.tool_results]
    assert {p["file"] for r in results for p in r["results"]} == {"leave.txt"}
    assert all("1 matching passages were left out" in r["note"] for r in results)
    assert {s["filename"] for s in final["sources"]} == {"leave.txt"}


async def test_a_knowledge_base_detached_after_approval_is_not_searched_and_the_run_goes_on(
    harness: SimpleNamespace,
) -> None:
    api = harness
    kb_id, _ = await knowledge_base(api, "Policies", {"leave.txt": LEAVE})
    api.gateway.child_script = [[search("annual leave")], None]
    api.gateway.proposal = json.dumps({"tasks": json.loads(api.gateway.proposal)["tasks"][:1]})
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    async with api.env.factory.begin() as db:
        await db.execute(
            delete(ProjectKnowledgeBase).where(ProjectKnowledgeBase.knowledge_base_id == kb_id)
        )
    (child,) = planned["tree"]["plan"]["children"]
    assert await job(api, root, child["dispatch_id"]) == "completed"
    assert await job(api, root) == "completed"
    final = await read(api, root)
    # The search ran and found nothing it may show; the task and the run completed.
    assert final["status"] == "completed" and final["sources"] == []
    (result,) = [json.loads(r) for r in api.gateway.tool_results]
    assert result["results"] == [] and "0 of 1 knowledge bases could be searched" in result["note"]


async def test_a_run_outside_a_matter_and_a_matter_without_knowledge_bases_search_none(
    harness: SimpleNamespace,
) -> None:
    api = harness
    await knowledge_base(api, "Policies", {"leave.txt": LEAVE})
    outside = await start_in_chat(api, await new_chat(api, in_project=False), profile=PROFILE)
    assert outside["planning"].get("knowledge_bases", []) == []
    assert await job(api, outside["root_id"]) == "completed"
    planned = await read(api, outside["root_id"])
    assert "KNOWLEDGE BASES" not in sections(plan_opening(api))
    assert planned["tree"]["plan"]["children"][0]["tools"]["analysis"] == ["read_note", "save_note"]
    # Archived, or another owner's: not listed for a run in the matter either.
    async with api.env.factory.begin() as db:
        await db.execute(update(KnowledgeBase).values(archived_at=datetime.now(UTC)))
    listed = (await api.client.get(f"{CHATS}/{await new_chat(api)}/run-documents")).json()
    assert listed["knowledge_bases"] == []
