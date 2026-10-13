"""ADR 0038, ruling 4: a run outside any matter reads a matter's file on that matter's terms.

A matter's inference-tier floor and privilege flag go with its files. A run
started from a chat in no matter has no terms of its own, so it takes on the
strictest of the matters that hold its selected documents: the lowest floor
any of them sets, and privileged if any of them is.

* The picker says what selecting such a file brings.
* The terms are set when the request is accepted, from the server's records.
* A route that cannot meet them is refused before anything is stored.
* They are worked out again at every admission, so a change stops the run
  before its next model call.

A run in a matter has that matter's terms, and still does not accept a file
that only another matter holds by upload or attachment. A selected file that
another matter holds through a knowledge base is the exception (ruled
2026-10-13): the run reads it under the stricter of the two matters' terms,
with the same four points.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from sqlalchemy import func, select, update
from tests.autonomous.orchestration.model_harness import (
    CHATS,
    job,
    messages,
    new_chat,
    read,
    run_to_completion,
    start_in_chat,
    tool_call,
)
from tests.autonomous.orchestration.test_document_runs import DPA, MSA, PROFILE
from tests.autonomous.orchestration.test_new_harness import approved, filed, requests_of

from app.api.chats import _load_history_messages
from app.autonomous.audit import RUN_PRIVILEGE_BASIS
from app.autonomous.orchestration.contracts import PreparedPlan
from app.autonomous.orchestration.reading import (
    NO_FLOOR,
    WITHHELD_ANSWER,
    MatterTerms,
    selection_terms,
    written_under_stricter_terms,
)
from app.autonomous.orchestration.store import _data_terms
from app.config import get_settings
from app.errors import Forbidden
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.document import Document
from app.models.file import File
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.orchestration import OrchestrationEffect as Effect, OrchestrationRoot
from app.models.project import Project, ProjectFile
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User

pytestmark = pytest.mark.integration

READ_FIRST = [[tool_call("read_document", {"document": 1, "reason": "Read."})], None]
REFUSED = "belongs to a matter whose inference tier floor or privilege setting"
ASSISTANT = "assistant"


@pytest.fixture
def harness(model_demo: SimpleNamespace) -> SimpleNamespace:
    """New harness on, with no floor of its own, so a matter's floor is the run's.

    The fixture route is tier 1, the strongest, and its gateway pseudonymizes
    at tier 1.
    """
    api = model_demo
    api.runtime.settings.new_harness_enabled = True
    api.runtime.settings.new_harness_minimum_tier = NO_FLOOR
    api.gateway.child_script = READ_FIRST
    api.gateway.child_answer = "The clause was read."
    api.gateway.synthesis_answer = "## Answer\n\nThe clause was read."
    return api


async def matter(
    api: SimpleNamespace,
    name: str,
    *,
    floor: int | None = None,
    privileged: bool = False,
    archived: bool = False,
    owner_id: UUID | None = None,
) -> UUID:
    """Another of the owner's matters, with its own terms."""
    async with api.env.factory.begin() as db:
        project = Project(
            owner_id=owner_id or api.env.owner_id,
            name=name,
            slug=f"terms-{uuid4()}",
            minimum_inference_tier=floor,
            privileged=privileged,
            archived_at=func.now() if archived else None,
        )
        db.add(project)
        await db.flush()
        return project.id


async def hold(api: SimpleNamespace, file_id: str, project_id: UUID) -> None:
    async with api.env.factory.begin() as db:
        db.add(ProjectFile(project_id=project_id, file_id=UUID(file_id)))


async def from_matter(api: SimpleNamespace, name: str, text: str, project_id: UUID) -> str:
    file_id = await filed(api, name, text)
    await hold(api, file_id, project_id)
    return file_id


async def in_knowledge_base(
    api: SimpleNamespace, file_id: str, project_id: UUID, *, archived: bool = False
) -> None:
    """File the file in a knowledge base that the matter has attached, and nowhere else."""
    async with api.env.factory.begin() as db:
        kb = KnowledgeBase(
            owner_id=api.env.owner_id,
            name=f"Knowledge base {uuid4().hex[:6]}",
            archived_at=func.now() if archived else None,
        )
        db.add(kb)
        await db.flush()
        db.add(KnowledgeBaseFile(kb_id=kb.id, file_id=UUID(file_id)))
        db.add(ProjectKnowledgeBase(project_id=project_id, knowledge_base_id=kb.id))


async def run_audit_rows(api: SimpleNamespace, root_id: str) -> list[AuditLog]:
    """Every audit row written for the run's root and its child sessions."""
    async with api.env.factory() as db:
        session_ids = [
            str(session_id)
            for session_id in (
                await db.scalars(
                    select(AutonomousSession.id).where(
                        AutonomousSession.root_session_id == UUID(root_id)
                    )
                )
            ).all()
        ]
        return list(
            (
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.resource_type == "autonomous_session",
                        AuditLog.resource_id.in_(session_ids),
                    )
                )
            ).all()
        )


async def listing(api: SimpleNamespace, chat_id: UUID, *file_ids: str) -> dict[str, Any]:
    response = await api.client.get(
        f"{CHATS}/{chat_id}/run-documents", params={"file_id": list(file_ids)}
    )
    assert response.status_code == 200, response.text
    return {d["filename"]: d for d in response.json()["documents"]}


async def stored_roots(api: SimpleNamespace) -> int:
    async with api.env.factory() as db:
        return len(
            (
                await db.scalars(
                    select(OrchestrationRoot.session_id).where(
                        OrchestrationRoot.owner_id == api.env.owner_id,
                        OrchestrationRoot.profile == PROFILE,
                    )
                )
            ).all()
        )


async def set_terms(api: SimpleNamespace, project_id: UUID, **values: Any) -> None:
    async with api.env.factory.begin() as db:
        await db.execute(update(Project).where(Project.id == project_id).values(**values))


# --- The picker says what a matter's file brings ------------------------------


async def test_the_picker_names_the_matters_and_their_strictest_terms(
    harness: SimpleNamespace,
) -> None:
    api = harness
    open_matter = await matter(api, "Open matter")
    floored = await matter(api, "Floored matter", floor=3)
    secret = await matter(api, "Privileged matter", floor=2, privileged=True)
    closed = await matter(api, "Archived matter", floor=1, archived=True)
    free = await filed(api, "free.txt", MSA)
    one = await from_matter(api, "one.txt", MSA, floored)
    both = await from_matter(api, "both.txt", DPA, floored)
    await hold(api, both, secret)
    await hold(api, both, open_matter)
    old = await from_matter(api, "old.txt", MSA, closed)

    chat_id = await new_chat(api, in_project=False)
    rows = await listing(api, chat_id, free, one, both, old)
    assert all(row["selectable"] and row["reason"] is None for row in rows.values())
    terms = {
        name: (
            sorted(row["matters"]),
            row["matter_minimum_inference_tier"],
            row["matter_privileged"],
        )
        for name, row in rows.items()
    }
    assert terms == {
        "free.txt": ([], None, False),
        "one.txt": (["Floored matter"], 3, False),
        # Every matter that holds it is named; the lowest floor, and privileged if any is.
        "both.txt": (["Floored matter", "Open matter", "Privileged matter"], 2, True),
        # Archiving a matter does not release its files from its terms.
        "old.txt": (["Archived matter"], 1, False),
    }


async def test_a_chat_in_a_matter_is_unchanged(harness: SimpleNamespace) -> None:
    """A file that only another matter holds, by attachment, is still refused."""
    api = harness
    other = await matter(api, "Other matter", floor=2)
    theirs = await from_matter(api, "theirs.txt", MSA, other)
    chat_id = await new_chat(api)
    rows = await listing(api, chat_id, theirs)
    row = rows["theirs.txt"]
    assert (row["selectable"], row["reason"]) == (False, "in_another_matter")
    # Nothing is said about terms a run in this matter would never take on.
    assert (row["matters"], row["matter_minimum_inference_tier"], row["matter_privileged"]) == (
        [],
        None,
        False,
    )
    refused = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[theirs], expect=400)
    assert refused["detail"]["details"]["reason"] == "in_another_matter"
    assert await stored_roots(api) == 0


# --- The run takes the terms on, from the server's records ---------------------


async def test_the_terms_of_a_set_of_documents_are_the_strictest_of_their_matters(
    harness: SimpleNamespace,
) -> None:
    api = harness
    floored = await matter(api, "Floored matter", floor=3)
    secret = await matter(api, "Privileged matter", floor=2, privileged=True)
    closed = await matter(api, "Archived matter", floor=1, archived=True)
    files = {
        "free": await filed(api, "free.txt", MSA),
        "floored": await from_matter(api, "one.txt", MSA, floored),
        "secret": await from_matter(api, "two.txt", DPA, secret),
        "closed": await from_matter(api, "three.txt", MSA, closed),
        # In the fixture matter by upload, which sets no floor.
        "uploaded": await filed(api, "four.txt", MSA, uploaded=True),
        # Uploaded straight into the floored matter: held by the file's own
        # project, with no attachment row.
        "uploaded_floored": await filed(api, "five.txt", MSA),
    }
    async with api.env.factory.begin() as db:
        await db.execute(
            update(File)
            .where(File.id == UUID(files["uploaded_floored"]))
            .values(project_id=floored)
        )
    async with api.env.factory() as db:
        ids = {
            name: await db.scalar(select(Document.id).where(Document.file_id == UUID(file_id)))
            for name, file_id in files.items()
        }

        async def terms(*names: str) -> MatterTerms:
            return await selection_terms(db, [ids[name] for name in names], lock=True)

        assert await terms() == MatterTerms(NO_FLOOR, False)
        assert await terms("free") == MatterTerms(NO_FLOOR, False)
        assert await terms("uploaded") == MatterTerms(NO_FLOOR, False)
        assert await terms("floored") == MatterTerms(3, False)
        assert await terms("uploaded_floored") == MatterTerms(3, False)
        assert await terms("free", "uploaded_floored") == MatterTerms(3, False)
        assert await terms("secret") == MatterTerms(2, True)
        assert await terms("free", "floored", "uploaded") == MatterTerms(3, False)
        assert await terms("floored", "secret") == MatterTerms(2, True)
        assert await terms("floored", "secret", "closed") == MatterTerms(1, True)


async def test_a_run_takes_on_the_floor_of_the_matter_its_document_comes_from(
    harness: SimpleNamespace,
) -> None:
    api = harness
    floored = await matter(api, "Floored matter", floor=3)
    contract = await from_matter(api, "msa.txt", MSA, floored)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    chat_id = await new_chat(api, in_project=False)

    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[contract])
    root = value["planning"]["root"]
    assert value["planning"]["project_id"] is None
    assert (root["minimum_inference_tier"], root["privileged"]) == (3, False)
    final = await run_to_completion(api, value)
    assert final["status"] == "completed"
    # Every call of the run asked the gateway for that floor, and none claimed privilege.
    assert {
        (r.minimum_inference_tier, r.lq_ai_project_minimum_inference_tier, r.lq_ai_privileged)
        for r in api.gateway.requests
    } == {(3, 3, False)}
    # The file was read where it is. Nothing was filed or attached anywhere else.
    assert "thirty (30) days" in json.dumps(api.gateway.tool_results)
    async with api.env.factory() as db:
        held = (
            await db.scalars(
                select(ProjectFile.project_id).where(ProjectFile.file_id == UUID(contract))
            )
        ).all()
        assert held == [floored]


async def test_a_run_with_a_privileged_matters_document_is_privileged_and_not_pseudonymized(
    harness: SimpleNamespace,
) -> None:
    """The gateway skips pseudonymization for privileged work, as it does in that matter."""
    api = harness
    secret = await matter(api, "Privileged matter", floor=1, privileged=True)
    advice = await from_matter(api, "msa.txt", MSA, secret)
    free = await filed(api, "free.txt", DPA)
    api.gateway.expected_documents = [
        {"number": 1, "filename": "free.txt"},
        {"number": 2, "filename": "msa.txt"},
    ]
    chat_id = await new_chat(api, in_project=False)

    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[free, advice])
    root = value["planning"]["root"]
    assert (root["minimum_inference_tier"], root["privileged"]) == (1, True)
    final = await run_to_completion(api, value)
    assert final["status"] == "completed"
    assert {(r.minimum_inference_tier, r.lq_ai_privileged) for r in api.gateway.requests} == {
        (1, True)
    }
    # Reported on every call's receipt, not assumed.
    effects = list(final["effects"]) + [
        e for child in final["tree"]["children"] for e in child["effects"]
    ]
    applied = {e["accounting"]["anonymization_applied"] for e in effects if e.get("accounting")}
    assert applied == {False}
    # Without the privileged file the same chat is pseudonymized as the operator set it.
    api.gateway.requests.clear()
    api.gateway.expected_documents = [{"number": 1, "filename": "free.txt"}]
    plain = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[free])
    assert plain["planning"]["root"]["privileged"] is False
    assert await job(api, plain["root_id"]) == "completed"
    (planning,) = (await read(api, plain["root_id"]))["effects"]
    assert planning["accounting"]["anonymization_applied"] is True


@pytest.mark.parametrize("archived", [False, True])
async def test_a_file_held_only_through_a_matters_knowledge_base_brings_that_matters_terms(
    harness: SimpleNamespace, archived: bool
) -> None:
    """A knowledge base's files are the matter's material, so its terms go with them.

    The file is neither uploaded to the matter nor attached to it, only in a
    knowledge base the matter has attached. Archiving the knowledge base does not
    release the file, as archiving a matter does not.
    """
    api = harness
    secret = await matter(api, "Privileged matter", floor=2, privileged=True)
    only_there = await filed(api, "kb-only.txt", MSA)
    await in_knowledge_base(api, only_there, secret, archived=archived)
    free = await filed(api, "free.txt", DPA)
    chat_id = await new_chat(api, in_project=False)

    rows = await listing(api, chat_id, only_there, free)
    kb_row = rows["kb-only.txt"]
    assert (
        kb_row["matters"],
        kb_row["matter_minimum_inference_tier"],
        kb_row["matter_privileged"],
    ) == (["Privileged matter"], 2, True)
    assert rows["free.txt"]["matters"] == []

    api.gateway.expected_documents = [{"number": 1, "filename": "kb-only.txt"}]
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[only_there])
    root = value["planning"]["root"]
    assert (root["minimum_inference_tier"], root["privileged"]) == (2, True)
    async with api.env.factory() as db:
        terms = await selection_terms(
            db, [(await db.scalar(select(Document.id).where(Document.file_id == UUID(only_there))))]
        )
    assert terms == MatterTerms(minimum_inference_tier=2, privileged=True)


async def test_the_audit_rows_of_a_run_outside_a_matter_carry_the_privilege_of_its_files(
    harness: SimpleNamespace,
) -> None:
    """The privileged-activity query must find a run that read a privileged matter's file."""
    api = harness
    secret = await matter(api, "Privileged matter", floor=1, privileged=True)
    advice = await from_matter(api, "msa.txt", MSA, secret)
    free = await filed(api, "free.txt", DPA)
    chat_id = await new_chat(api, in_project=False)

    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    privileged = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[advice])
    final = await run_to_completion(api, privileged)
    assert final["status"] == "completed"
    rows = await run_audit_rows(api, privileged["root_id"])
    families = {row.action.split(".")[0] for row in rows}
    # Both writers: the run's own events and the chokepoint's session events.
    assert families == {"orchestration", "autonomous_session"}
    assert all(row.privilege_marked and row.privilege_basis for row in rows), [
        (row.action, row.privilege_marked) for row in rows if not row.privilege_marked
    ]

    # The same chat with a file no matter holds is marked as any other row is.
    api.gateway.expected_documents = [{"number": 1, "filename": "free.txt"}]
    plain = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[free])
    assert (await run_to_completion(api, plain))["status"] == "completed"
    plain_rows = await run_audit_rows(api, plain["root_id"])
    assert plain_rows
    assert not any(row.privilege_marked or row.privilege_basis for row in plain_rows)


@pytest.mark.parametrize("borrows", [False, True])
async def test_the_audit_rows_of_a_run_in_a_privileged_matter_carry_the_matters_privilege(
    harness: SimpleNamespace, borrows: bool
) -> None:
    """The basis is the matter, also when the run reads a privileged lending matter's file."""
    api = harness
    await set_terms(api, api.env.project_id, privileged=True, minimum_inference_tier=1)
    chat_id = await new_chat(api)
    document = await filed(api, "msa.txt", MSA)
    if borrows:
        lender = await matter(api, "Lending matter", floor=1, privileged=True)
        await in_knowledge_base(api, document, lender)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[document])
    assert (await run_to_completion(api, value))["status"] == "completed"
    rows = await run_audit_rows(api, value["root_id"])
    assert {row.action.split(".")[0] for row in rows} == {"orchestration", "autonomous_session"}
    assert {(row.privilege_marked, row.privilege_basis) for row in rows} == {
        (True, "project:Fixture")
    }


async def test_a_direct_answer_is_made_under_the_selected_documents_terms(
    harness: SimpleNamespace,
) -> None:
    """The planning call is shown the thread and the file names, so the terms apply to it too."""
    api = harness
    secret = await matter(api, "Privileged matter", floor=1, privileged=True)
    advice = await from_matter(api, "msa.txt", MSA, secret)
    api.gateway.direct_answer = "You're welcome."
    chat_id = await new_chat(api, in_project=False)

    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[advice])
    assert await job(api, value["root_id"]) == "completed"
    answered = await read(api, value["root_id"])
    assert answered["status"] == "completed" and answered["answered_directly"] is True
    (request,) = requests_of(api, "propose_plan")
    assert (request.minimum_inference_tier, request.lq_ai_privileged) == (1, True)


# --- A route that cannot meet the terms is refused before anything is stored ----


async def test_a_route_weaker_than_the_matters_floor_is_refused_and_says_why(
    harness: SimpleNamespace,
) -> None:
    api = harness
    api.gateway.config["providers"][0]["tier"] = 3
    api.gateway.config["anonymization"] = {"enabled": True, "apply_at_tiers": []}
    strict = await matter(api, "Strict matter", floor=2)
    contract = await from_matter(api, "msa.txt", MSA, strict)
    free = await filed(api, "free.txt", DPA)
    chat_id = await new_chat(api, in_project=False)

    refused = await start_in_chat(
        api, chat_id, profile=PROFILE, file_ids=[free, contract], expect=403
    )
    assert REFUSED in refused["detail"]["message"]
    assert refused["detail"]["details"] == {"minimum_inference_tier": 2, "privileged": False}
    # Nothing was stored, written or sent.
    assert await stored_roots(api) == 0
    assert await messages(api, chat_id) == [] and api.gateway.requests == []

    # The same route serves the chat with a file that brings no terms.
    api.gateway.expected_documents = [{"number": 1, "filename": "free.txt"}]
    accepted = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[free])
    assert accepted["planning"]["root"]["minimum_inference_tier"] == NO_FLOOR


async def test_a_route_that_is_unavailable_anyway_is_not_blamed_on_the_matter(
    harness: SimpleNamespace,
) -> None:
    api = harness
    api.gateway.config["cost_tracking"]["enabled"] = False
    strict = await matter(api, "Strict matter", floor=2)
    contract = await from_matter(api, "msa.txt", MSA, strict)
    chat_id = await new_chat(api, in_project=False)

    refused = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[contract], expect=403)
    assert REFUSED not in refused["detail"]["message"]
    assert await stored_roots(api) == 0


# --- The terms are worked out again at every admission -------------------------


@pytest.mark.parametrize(
    "change",
    [
        # The matter becomes privileged: the run would send it pseudonymized, or elsewhere.
        "matter_becomes_privileged",
        # The matter's floor tightens below the tier the run was approved for.
        "floor_tightens",
        # The file is also filed in a stricter matter.
        "filed_in_a_stricter_matter",
    ],
)
async def test_terms_that_tighten_after_approval_stop_the_run_before_its_next_call(
    harness: SimpleNamespace, change: str
) -> None:
    api = harness
    floored = await matter(api, "Floored matter", floor=3)
    contract = await from_matter(api, "msa.txt", MSA, floored)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    chat_id = await new_chat(api, in_project=False)
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[contract])
    children = await approved(api, value)

    if change == "matter_becomes_privileged":
        await set_terms(api, floored, privileged=True)
    elif change == "floor_tightens":
        await set_terms(api, floored, minimum_inference_tier=2)
    else:
        await hold(api, contract, await matter(api, "Stricter matter", floor=1, privileged=True))

    sent = len(api.gateway.requests)
    for child in children:
        assert await job(api, value["root_id"], child) == "stopped"
    assert len(api.gateway.requests) == sent
    async with api.env.factory() as db:
        reads = select(Effect.effect_key).where(
            Effect.intent == "retrieve_chunks", Effect.session_id.in_([UUID(c) for c in children])
        )
        assert not (await db.scalars(reads)).all()
    # The owner can still read the run and what stopped.
    assert (await read(api, value["root_id"]))["status"] != "completed"


async def test_a_privilege_flag_whose_matter_is_no_longer_privileged_stops_the_run(
    harness: SimpleNamespace,
) -> None:
    """The flag turns pseudonymization off, so it is not kept without a privileged matter behind it."""
    api = harness
    secret = await matter(api, "Privileged matter", floor=1, privileged=True)
    advice = await from_matter(api, "msa.txt", MSA, secret)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    chat_id = await new_chat(api, in_project=False)
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[advice])
    assert value["planning"]["root"]["privileged"] is True
    children = await approved(api, value)

    await set_terms(api, secret, privileged=False)
    sent = len(api.gateway.requests)
    for child in children:
        assert await job(api, value["root_id"], child) == "stopped"
    assert len(api.gateway.requests) == sent


async def test_terms_that_loosen_or_stay_as_they_were_do_not_stop_the_run(
    harness: SimpleNamespace,
) -> None:
    api = harness
    floored = await matter(api, "Floored matter", floor=3)
    contract = await from_matter(api, "msa.txt", MSA, floored)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    chat_id = await new_chat(api, in_project=False)
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[contract])
    children = await approved(api, value)

    # A weaker floor allows what was approved; a second matter with no terms adds none.
    await set_terms(api, floored, minimum_inference_tier=4)
    await hold(api, contract, await matter(api, "Open matter"))
    for child in children:
        assert await job(api, value["root_id"], child) == "completed"
    assert await job(api, value["root_id"]) == "completed"
    final = await read(api, value["root_id"])
    assert final["status"] == "completed"
    # It ran on the terms it was approved under, not the looser ones.
    assert {r.minimum_inference_tier for r in api.gateway.requests} == {3}


# --- A run in a matter that reads a file from another matter's knowledge base ---
#
# Ruled 2026-10-13. The file is held by the other matter (the lending matter)
# only through a knowledge base it has attached. A run in this matter may read
# it, and runs under the stricter of the two matters' terms.


async def lent(api: SimpleNamespace, name: str, text: str, lender: UUID) -> str:
    """A file that ``lender`` holds only through a knowledge base it has attached."""
    file_id = await filed(api, name, text)
    await in_knowledge_base(api, file_id, lender)
    return file_id


def terms_sent(api: SimpleNamespace) -> set[tuple[int, int, bool]]:
    """The floor, the matter floor and the privilege flag of every request the gateway got."""
    return {
        (r.minimum_inference_tier, r.lq_ai_project_minimum_inference_tier, r.lq_ai_privileged)
        for r in api.gateway.requests
    }


async def attached_here(api: SimpleNamespace, file_id: str) -> bool:
    async with api.env.factory() as db:
        return await db.get(ProjectFile, (api.env.project_id, UUID(file_id))) is not None


def root_terms(value: dict[str, Any]) -> tuple[int, bool]:
    root = value["planning"]["root"]
    return root["minimum_inference_tier"], root["privileged"]


@pytest.mark.parametrize(
    ("floor", "privileged"),
    [
        # A floor alone, privilege alone with a floor any route meets, and both.
        (3, False),
        (NO_FLOOR, True),
        (2, True),
    ],
)
async def test_a_run_in_a_matter_takes_on_the_terms_of_a_matter_whose_knowledge_base_holds_its_file(
    harness: SimpleNamespace, floor: int, privileged: bool
) -> None:
    """The fixture matter sets no terms, so the lending matter's are the stricter."""
    api = harness
    lender = await matter(api, "Lending matter", floor=floor, privileged=privileged)
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    api.gateway.expected_documents = [{"number": 1, "filename": "kb-only.txt"}]
    chat_id = await new_chat(api)

    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed])
    assert value["planning"]["project_id"] == str(api.env.project_id)
    assert value["planning"]["documents"][0]["attached_for_run"] is True
    assert root_terms(value) == (floor, privileged)
    assert (await run_to_completion(api, value))["status"] == "completed"
    # Every call of the run went out with that floor and that flag.
    assert terms_sent(api) == {(floor, floor, privileged)}
    assert "thirty (30) days" in json.dumps(api.gateway.tool_results)

    # The pick attached the file here. A second run that selects it, now one of
    # this matter's own files, does not escape the lending matter's terms.
    assert await attached_here(api, borrowed)
    api.gateway.requests.clear()
    again = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed])
    assert again["planning"]["documents"][0]["attached_for_run"] is False
    assert root_terms(again) == (floor, privileged)
    assert (await run_to_completion(api, again))["status"] == "completed"
    assert terms_sent(api) == {(floor, floor, privileged)}


@pytest.mark.parametrize(
    ("here", "there", "expected"),
    [
        # Term by term: the lower floor, and privileged if either matter is.
        ((2, False), (3, True), (2, True)),
        ((3, True), (2, False), (2, True)),
        ((1, True), (None, False), (1, True)),
    ],
)
async def test_the_stricter_of_the_two_matters_terms_applies_term_by_term(
    harness: SimpleNamespace,
    here: tuple[int, bool],
    there: tuple[int | None, bool],
    expected: tuple[int, bool],
) -> None:
    api = harness
    await set_terms(api, api.env.project_id, minimum_inference_tier=here[0], privileged=here[1])
    lender = await matter(api, "Lending matter", floor=there[0], privileged=there[1])
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    api.gateway.expected_documents = [{"number": 1, "filename": "kb-only.txt"}]
    chat_id = await new_chat(api)

    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed])
    assert root_terms(value) == expected
    assert await job(api, value["root_id"]) == "completed"
    (request,) = requests_of(api, "propose_plan")
    assert (request.minimum_inference_tier, request.lq_ai_privileged) == expected


async def test_a_route_weaker_than_the_lending_matters_floor_is_refused_before_anything_is_stored(
    harness: SimpleNamespace,
) -> None:
    api = harness
    api.gateway.config["providers"][0]["tier"] = 3
    api.gateway.config["anonymization"] = {"enabled": True, "apply_at_tiers": []}
    lender = await matter(api, "Lending matter", floor=2)
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    ours = await filed(api, "ours.txt", DPA)
    chat_id = await new_chat(api)

    refused = await start_in_chat(
        api, chat_id, profile=PROFILE, file_ids=[ours, borrowed], expect=403
    )
    assert refused["detail"]["message"] == (
        "A selected document belongs to a matter whose inference tier floor "
        "or privilege setting this run's route does not meet."
    )
    assert refused["detail"]["details"] == {"minimum_inference_tier": 2, "privileged": False}
    # Nothing was stored, written, attached or sent.
    assert await stored_roots(api) == 0
    assert await messages(api, chat_id) == [] and api.gateway.requests == []
    assert not await attached_here(api, borrowed) and not await attached_here(api, ours)

    # The same route serves this matter with a file that brings no terms.
    api.gateway.expected_documents = [{"number": 1, "filename": "ours.txt"}]
    accepted = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[ours])
    assert root_terms(accepted) == (NO_FLOOR, False)


@pytest.mark.parametrize("why", ["the_route_is_not_priced", "this_matters_own_floor_is_not_met"])
async def test_a_route_this_matter_cannot_use_anyway_is_not_blamed_on_the_lending_matter(
    harness: SimpleNamespace, why: str
) -> None:
    """The comparison is this matter's own terms, not a chat with none."""
    api = harness
    if why == "the_route_is_not_priced":
        api.gateway.config["cost_tracking"]["enabled"] = False
    else:
        api.gateway.config["providers"][0]["tier"] = 3
        api.gateway.config["anonymization"] = {"enabled": True, "apply_at_tiers": []}
        await set_terms(api, api.env.project_id, minimum_inference_tier=2)
    lender = await matter(api, "Lending matter", floor=1)
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    chat_id = await new_chat(api)

    refused = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed], expect=403)
    assert REFUSED not in refused["detail"]["message"]
    assert await stored_roots(api) == 0
    assert not await attached_here(api, borrowed)


@pytest.mark.parametrize(
    "change",
    [
        "the_lending_matter_becomes_privileged",
        "the_lending_matters_floor_tightens",
        # The file is put in the knowledge base of a second, stricter matter.
        "a_stricter_matters_knowledge_base_takes_the_file",
    ],
)
async def test_a_lending_matter_whose_terms_tighten_after_approval_stops_the_run(
    harness: SimpleNamespace, change: str
) -> None:
    api = harness
    lender = await matter(api, "Lending matter", floor=3)
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    api.gateway.expected_documents = [{"number": 1, "filename": "kb-only.txt"}]
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed])
    children = await approved(api, value)
    planned = await read(api, value["root_id"])

    if change == "the_lending_matter_becomes_privileged":
        await set_terms(api, lender, privileged=True)
    elif change == "the_lending_matters_floor_tightens":
        await set_terms(api, lender, minimum_inference_tier=2)
    else:
        stricter = await matter(api, "Stricter matter", floor=1, privileged=True)
        await in_knowledge_base(api, borrowed, stricter)

    sent = len(api.gateway.requests)
    for child in children:
        assert await job(api, value["root_id"], child) == "stopped"
    assert len(api.gateway.requests) == sent
    async with api.env.factory() as db:
        reads = select(Effect.effect_key).where(
            Effect.intent == "retrieve_chunks", Effect.session_id.in_([UUID(c) for c in children])
        )
        assert not (await db.scalars(reads)).all()
        # The refusal is the one a matter's own changed terms give.
        plan = PreparedPlan.model_validate_json(json.dumps(planned["tree"]["plan"]))
        here = await db.get(Project, api.env.project_id)
        with pytest.raises(Forbidden, match="Project data policy has changed"):
            await _data_terms(db, here, plan)
    assert (await read(api, value["root_id"]))["status"] != "completed"


async def test_a_lending_matter_whose_terms_loosen_does_not_stop_the_run(
    harness: SimpleNamespace,
) -> None:
    api = harness
    lender = await matter(api, "Lending matter", floor=3, privileged=True)
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    api.gateway.expected_documents = [{"number": 1, "filename": "kb-only.txt"}]
    chat_id = await new_chat(api)
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed])
    assert root_terms(value) == (3, True)
    children = await approved(api, value)

    # A weaker floor and no privilege flag allow what was approved.
    await set_terms(api, lender, minimum_inference_tier=4, privileged=False)
    for child in children:
        assert await job(api, value["root_id"], child) == "completed"
    assert await job(api, value["root_id"]) == "completed"
    assert (await read(api, value["root_id"]))["status"] == "completed"
    # It ran on the terms it was approved under, not the looser ones.
    assert terms_sent(api) == {(3, 3, True)}


async def test_the_audit_rows_of_a_run_made_privileged_by_a_lending_matter_are_marked(
    harness: SimpleNamespace,
) -> None:
    """This matter is not privileged, so marking from it alone would leave the rows unmarked."""
    api = harness
    lender = await matter(api, "Lending matter", floor=1, privileged=True)
    borrowed = await lent(api, "kb-only.txt", MSA, lender)
    ours = await filed(api, "ours.txt", DPA, attached=True)
    chat_id = await new_chat(api)

    api.gateway.expected_documents = [{"number": 1, "filename": "kb-only.txt"}]
    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[borrowed])
    assert root_terms(value) == (1, True)
    assert (await run_to_completion(api, value))["status"] == "completed"
    rows = await run_audit_rows(api, value["root_id"])
    # Both writers: the run's own events and the chokepoint's session events.
    assert {row.action.split(".")[0] for row in rows} == {"orchestration", "autonomous_session"}
    assert {(row.privilege_marked, row.privilege_basis) for row in rows} == {
        (True, RUN_PRIVILEGE_BASIS)
    }, [(row.action, row.privilege_basis) for row in rows]

    # A run in the same matter without the file is marked as before: not at all.
    api.gateway.expected_documents = [{"number": 1, "filename": "ours.txt"}]
    plain = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[ours])
    assert (await run_to_completion(api, plain))["status"] == "completed"
    plain_rows = await run_audit_rows(api, plain["root_id"])
    assert plain_rows
    assert not any(row.privilege_marked or row.privilege_basis for row in plain_rows)


async def test_a_candidate_another_matter_holds_by_attachment_is_refused_whatever_else_holds_it(
    harness: SimpleNamespace,
) -> None:
    """Unchanged: a knowledge base elsewhere does not make another matter's file selectable."""
    api = harness
    other = await matter(api, "Other matter", floor=2)
    lender = await matter(api, "Lending matter", floor=1, privileged=True)
    theirs = await from_matter(api, "theirs.txt", MSA, other)
    await in_knowledge_base(api, theirs, lender)
    chat_id = await new_chat(api)

    row = (await listing(api, chat_id, theirs))["theirs.txt"]
    assert (row["selectable"], row["reason"]) == (False, "in_another_matter")
    # Nothing is said about terms for a file a run here would never read.
    assert (row["matters"], row["matter_minimum_inference_tier"], row["matter_privileged"]) == (
        [],
        None,
        False,
    )
    refused = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[theirs], expect=400)
    assert refused["detail"]["details"]["reason"] == "in_another_matter"
    assert await stored_roots(api) == 0 and not await attached_here(api, theirs)


async def test_a_run_that_borrows_nothing_runs_on_its_own_matters_terms_as_before(
    harness: SimpleNamespace,
) -> None:
    """Unchanged: attachment to a second matter, and this matter's own knowledge base, add no terms."""
    api = harness
    strict = await matter(api, "Strict matter", floor=2, privileged=True)
    # Attached to both matters: the owner's own earlier action, read on this matter's terms.
    both = await filed(api, "both.txt", MSA, attached=True)
    await hold(api, both, strict)
    # In this matter's own knowledge base, and a candidate that no matter holds.
    own = await filed(api, "own-kb.txt", DPA, attached=True)
    await in_knowledge_base(api, own, api.env.project_id)
    free = await filed(api, "free.txt", DPA)
    # The strict matter lends a file that this run does not select.
    await lent(api, "unselected.txt", MSA, strict)
    api.gateway.expected_documents = [
        {"number": 1, "filename": "both.txt"},
        {"number": 2, "filename": "own-kb.txt"},
        {"number": 3, "filename": "free.txt"},
    ]
    chat_id = await new_chat(api)

    value = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[both, own, free])
    assert root_terms(value) == (NO_FLOOR, False)
    assert (await run_to_completion(api, value))["status"] == "completed"
    assert terms_sent(api) == {(NO_FLOOR, NO_FLOOR, False)}
    rows = await run_audit_rows(api, value["root_id"])
    assert rows and not any(row.privilege_marked or row.privilege_basis for row in rows)


async def test_the_picker_in_a_matter_names_the_lending_matters_and_their_terms(
    harness: SimpleNamespace,
) -> None:
    api = harness
    async with api.env.factory.begin() as db:
        stranger = User(email=f"stranger-{uuid4()}@example.com", hashed_password="unused-test")
        db.add(stranger)
        await db.flush()
        stranger_id = stranger.id
    lender = await matter(api, "Lending matter", floor=2, privileged=True)
    closed = await matter(api, "Archived matter", floor=3, archived=True)
    open_matter = await matter(api, "Open matter")
    someone_elses = await matter(api, "Someone else's matter", floor=1, owner_id=stranger_id)
    # A candidate, not yet attached here, and a file that already is.
    candidate = await lent(api, "candidate.txt", MSA, lender)
    attached = await filed(api, "attached.txt", DPA, attached=True)
    await in_knowledge_base(api, attached, lender)
    await in_knowledge_base(api, attached, closed)
    unfloored = await lent(api, "open.txt", MSA, open_matter)
    unnamed = await lent(api, "unnamed.txt", MSA, someone_elses)
    # Files that bring nothing: this matter's own, and one in its own knowledge base.
    await filed(api, "plain.txt", MSA, attached=True)
    own = await filed(api, "own-kb.txt", DPA, attached=True)
    await in_knowledge_base(api, own, api.env.project_id)

    chat_id = await new_chat(api)
    rows = await listing(api, chat_id, candidate, unfloored, unnamed)
    expected = {
        "candidate.txt": (["Lending matter"], 2, True),
        # Every lending matter is named, an archived one too; the lowest floor,
        # and privileged if any is.
        "attached.txt": (["Archived matter", "Lending matter"], 2, True),
        "open.txt": (["Open matter"], None, False),
        # Another owner's matter counts for the terms and is not named.
        "unnamed.txt": ([], 1, False),
        "plain.txt": ([], None, False),
        # This matter is not a matter the run borrows from.
        "own-kb.txt": ([], None, False),
    }
    assert all(rows[name]["selectable"] and rows[name]["reason"] is None for name in expected)
    assert {
        name: (
            sorted(rows[name]["matters"]),
            rows[name]["matter_minimum_inference_tier"],
            rows[name]["matter_privileged"],
        )
        for name in expected
    } == expected


# --- An answer written under a matter's terms is not shown to a run without them ---


def thread_of(value: dict[str, Any]) -> list[tuple[str, str]]:
    """The chat as the run's planning call was shown it, frozen in its intake."""
    return [(m["role"], m["content"]) for m in value["planning"]["thread"]]


@pytest.mark.parametrize(
    ("floor", "privileged"),
    [
        # Privileged: a later run without the file would be pseudonymized, or routed as the chat alone.
        (1, True),
        # A floor alone: a later run without the file could go to a weaker route.
        (2, False),
        # Privilege alone, with a floor any route meets: only the flag differs.
        (NO_FLOOR, True),
    ],
)
async def test_an_answer_written_under_a_matters_terms_is_not_shown_to_a_later_run_without_them(
    harness: SimpleNamespace, floor: int, privileged: bool
) -> None:
    """Found in review. The answer may hold what the matter's file said.

    A run outside any matter takes its terms from the documents selected for
    it. A follow-up that keeps the earlier run's documents has its terms and is
    shown its answer; one that drops them is shown a note in its place.
    """
    api = harness
    held = await matter(api, "Strict matter", floor=floor, privileged=privileged)
    advice = await from_matter(api, "msa.txt", MSA, held)
    free = await filed(api, "free.txt", DPA)
    answer = "## Answer\n\nONLY-IN-THE-MATTER: fees are due in thirty days."
    api.gateway.synthesis_answer = answer
    chat_id = await new_chat(api, in_project=False)

    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    first = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[advice])
    assert (await run_to_completion(api, first))["status"] == "completed"
    assert [m["content"] for m in await messages(api, chat_id)][1] == answer

    # Dropped: no document, and a document that brings no terms.
    for file_ids, listed in (([], []), ([free], [{"number": 1, "filename": "free.txt"}])):
        api.gateway.expected_documents = listed
        api.gateway.requests.clear()
        later = await start_in_chat(
            api, chat_id, profile=PROFILE, goal="Shorten that.", file_ids=file_ids
        )
        root = later["planning"]["root"]
        assert (root["minimum_inference_tier"], root["privileged"]) == (NO_FLOOR, False)
        shown = thread_of(later)
        assert (ASSISTANT, WITHHELD_ANSWER) in shown
        assert "ONLY-IN-THE-MATTER" not in json.dumps(later["planning"])
        # And it is what the model was sent, not only what was stored.
        assert await job(api, later["root_id"]) == "completed"
        (planning,) = requests_of(api, "propose_plan")
        sent = json.dumps([m.content for m in planning.messages])
        assert "ONLY-IN-THE-MATTER" not in sent and "An earlier answer is not shown here" in sent
        # The owner's own request of that turn is theirs, and is shown.
        assert ("user", first["planning"]["goal"]) in shown
        halted = await api.client.post(
            f"/api/v1/autonomous/orchestration/chat-runs/{later['root_id']}/halt"
        )
        assert halted.status_code == 200

    # Kept: the same document, so the same terms, and the answer is there to follow up on.
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    kept = await start_in_chat(
        api, chat_id, profile=PROFILE, goal="Shorten that.", file_ids=[advice]
    )
    assert (ASSISTANT, answer) in thread_of(kept)
    assert WITHHELD_ANSWER not in json.dumps(kept["planning"])


@pytest.mark.parametrize(
    ("floor", "privileged"),
    [(1, True), (2, False), (NO_FLOOR, True)],
)
@respx.mock
async def test_an_answer_written_under_a_matters_terms_is_not_replayed_to_an_ordinary_turn(
    harness: SimpleNamespace, floor: int, privileged: bool
) -> None:
    """Ruled 2026-10-13. Terms follow the file into a follow-up that is not a run.

    An ordinary turn replays the thread to the provider. In a chat that is in
    no matter it has no floor and no privilege flag, so an answer a run wrote
    under a matter's terms would leave on weaker ones. The ordinary turn is
    sent the same note a later run is shown, and the owner's own messages.
    """
    api = harness
    held = await matter(api, "Strict matter", floor=floor, privileged=privileged)
    advice = await from_matter(api, "msa.txt", MSA, held)
    answer = "## Answer\n\nONLY-IN-THE-MATTER: fees are due in thirty days."
    api.gateway.synthesis_answer = answer
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    chat_id = await new_chat(api, in_project=False)
    first = await start_in_chat(api, chat_id, profile=PROFILE, file_ids=[advice])
    assert (await run_to_completion(api, first))["status"] == "completed"
    assert [m["content"] for m in await messages(api, chat_id)][1] == answer

    async def replayed(terms: MatterTerms | None) -> list[tuple[str, str]]:
        async with api.env.factory() as db:
            history = await _load_history_messages(
                db,
                chat_id=chat_id,
                exclude_message_id=uuid4(),
                token_budget=100_000,
                max_messages=50,
                terms=terms,
            )
        return [(m.role, str(m.content)) for m in history]

    # A turn with no terms of its own, and one whose matter is weaker than the run's.
    weaker = MatterTerms(minimum_inference_tier=NO_FLOOR, privileged=False)
    assert replayed_answer(await replayed(weaker)) == WITHHELD_ANSWER
    # A turn under the same terms, as in the matter the file belongs to, is shown it.
    assert replayed_answer(await replayed(MatterTerms(floor, privileged))) == answer
    # The owner's own request of that turn is theirs, and is replayed either way.
    assert ("user", first["planning"]["goal"]) in await replayed(weaker)

    # And it is what the route sends, not only what the loader returns.
    route = respx.post(f"{get_settings().lq_ai_gateway_url}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-follow-up",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "native",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Shorter."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
                "routed_inference_tier": 3,
                "routed_provider": "selected",
                "cost_estimate": 0.0,
            },
        )
    )
    response = await api.client.post(
        f"{CHATS}/{chat_id}/messages", json={"content": "Shorten that.", "model": "smart"}
    )
    assert response.status_code == 200, response.text
    sent = route.calls[0].request.read().decode()
    assert "ONLY-IN-THE-MATTER" not in sent
    assert "An earlier answer is not shown here" in sent
    assert first["planning"]["goal"] in sent


def replayed_answer(history: list[tuple[str, str]]) -> str:
    (content,) = [content for role, content in history if role == ASSISTANT]
    return content


async def test_an_ordinary_turn_in_the_runs_own_matter_is_shown_its_answer(
    harness: SimpleNamespace,
) -> None:
    """Nothing is withheld from a follow-up in the matter the run ran in."""
    api = harness
    answer = "## Answer\n\nFees are due in thirty days."
    api.gateway.synthesis_answer = answer
    api.gateway.expected_documents = []
    api.gateway.child_script = [None]
    await set_terms(api, api.env.project_id, minimum_inference_tier=2)
    chat_id = await new_chat(api)
    first = await start_in_chat(api, chat_id, profile=PROFILE)
    assert (await run_to_completion(api, first))["status"] == "completed"
    async with api.env.factory() as db:
        history = await _load_history_messages(
            db,
            chat_id=chat_id,
            exclude_message_id=uuid4(),
            token_budget=100_000,
            max_messages=50,
            terms=MatterTerms(minimum_inference_tier=2, privileged=False),
        )
    assert (ASSISTANT, answer) in [(m.role, m.content) for m in history]


async def test_an_earlier_answer_is_shown_where_the_terms_are_the_same_or_stricter(
    harness: SimpleNamespace,
) -> None:
    """Nothing is withheld between runs of one matter, or from a run that is stricter."""
    api = harness
    answer = "## Answer\n\nFees are due in thirty days."
    api.gateway.synthesis_answer = answer
    api.gateway.expected_documents = []
    api.gateway.child_script = [None]

    # Two runs in the fixture matter.
    inside = await new_chat(api)
    assert (await run_to_completion(api, await start_in_chat(api, inside, profile=PROFILE)))[
        "status"
    ] == "completed"
    again = await start_in_chat(api, inside, profile=PROFILE, goal="Shorten that.")
    assert (ASSISTANT, answer) in thread_of(again)
    assert (
        await api.client.post(f"/api/v1/autonomous/orchestration/chat-runs/{again['root_id']}/halt")
    ).status_code == 200

    # A run with no terms, then one in the same chat that takes a privileged matter's on.
    outside = await new_chat(api, in_project=False)
    assert (await run_to_completion(api, await start_in_chat(api, outside, profile=PROFILE)))[
        "status"
    ] == "completed"
    secret = await matter(api, "Privileged matter", floor=1, privileged=True)
    advice = await from_matter(api, "msa.txt", MSA, secret)
    api.gateway.expected_documents = [{"number": 1, "filename": "msa.txt"}]
    stricter = await start_in_chat(
        api, outside, profile=PROFILE, goal="Check it against this.", file_ids=[advice]
    )
    assert stricter["planning"]["root"]["privileged"] is True
    assert (ASSISTANT, answer) in thread_of(stricter)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("earlier", "now", "stricter"),
    [
        ({"minimum_inference_tier": 5, "privileged": False}, MatterTerms(5, False), False),
        ({"minimum_inference_tier": 2, "privileged": False}, MatterTerms(2, False), False),
        ({"minimum_inference_tier": 3, "privileged": False}, MatterTerms(2, False), False),
        ({"minimum_inference_tier": 1, "privileged": True}, MatterTerms(1, True), False),
        ({"minimum_inference_tier": 5, "privileged": False}, MatterTerms(1, True), False),
        # A lower floor then, or privilege then and none now.
        ({"minimum_inference_tier": 2, "privileged": False}, MatterTerms(3, False), True),
        ({"minimum_inference_tier": 1, "privileged": True}, MatterTerms(1, False), True),
        ({"minimum_inference_tier": 5, "privileged": True}, MatterTerms(5, False), True),
        # Terms that cannot be read are treated as stricter: withheld, not guessed.
        ({"minimum_inference_tier": "1", "privileged": False}, MatterTerms(5, False), True),
        ({"minimum_inference_tier": 5}, MatterTerms(5, False), True),
        ({}, MatterTerms(5, False), True),
        (None, MatterTerms(5, False), True),
    ],
)
def test_which_earlier_terms_count_as_stricter(
    earlier: dict[str, Any] | None, now: MatterTerms, stricter: bool
) -> None:
    snapshot = None if earlier is None else {"root": earlier}
    assert written_under_stricter_terms(snapshot, now) is stricter
    if earlier is not None:
        # An intake with no scope at all, or one that is not an object.
        assert written_under_stricter_terms({"root": "x"}, now) is True
