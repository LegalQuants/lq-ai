"""ADR 0038, ruling 10: what a role may do with a governed run.

* A read-only role (``viewer``, ``auditor``) cannot start a run, approve a plan
  or reject one. The route refuses, and so does the store behind it.
* A viewer still reads their own run and can halt it: halting only narrows
  authority.
* An admin or an auditor with matter read access may read another owner's run, its plan and how its
  sessions were set up. Each such read writes one audit row. They cannot act
  on it, and the route that serves a working file refuses them. That route
  protects less than it sounds: a task's findings are in the tree, and a note
  a task saved is in its trace, so both are read without it. The last test
  pins that, so the documents cannot claim otherwise.
* Anyone else gets the 404 a missing run gets, and no audit row is written.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from tests.autonomous.orchestration.model_harness import (
    BASE,
    CHATS,
    GOAL,
    job,
    new_chat,
    read,
    run_to_completion,
    start_in_chat,
    tool_call,
)

from app.api.dependencies import get_active_user
from app.api.orchestration import begin_run
from app.errors import Forbidden, NotFound
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat
from app.models.orchestration import OrchestrationRoot
from app.models.project_member import ProjectMember
from app.models.user import User

pytestmark = pytest.mark.integration

PROFILE = "new_harness_v1"
READ_ONLY = "Starting, approving and rejecting a run requires a member or admin role"


@pytest_asyncio.fixture
async def roles(model_demo: SimpleNamespace) -> AsyncIterator[SimpleNamespace]:
    """New harness on, with a way to act as the owner in another role or as someone else."""
    api = model_demo
    api.runtime.settings.new_harness_enabled = True
    api.gateway.child_script = [None]
    api.gateway.expected_documents = []
    api.gateway.child_answer = "From general knowledge only; no document was read."
    api.gateway.synthesis_answer = "## Answer\n\nFrom general knowledge only."
    created: list[UUID] = []

    async def someone(role: str, *, admin: bool = False, matter_read: bool = False) -> User:
        async with api.env.factory.begin() as db:
            user = User(
                email=f"{role}-{uuid4()}@example.com",
                hashed_password="unused-test",
                autonomous_enabled=True,
                role=role,
                is_admin=admin,
            )
            db.add(user)
            await db.flush()
            created.append(user.id)
            if matter_read:
                db.add(ProjectMember(project_id=api.env.project_id, user_id=user.id, role="reader"))
            return user

    async def owner_as(role: str) -> User:
        """The run's owner, with their role changed as an administrator would change it."""
        async with api.env.factory.begin() as db:
            await db.execute(update(User).where(User.id == api.env.owner_id).values(role=role))
        async with api.env.factory() as db:
            owner = await db.get(User, api.env.owner_id)
        assert owner is not None
        act_as(owner)
        return owner

    def act_as(user: User) -> None:
        app.dependency_overrides[get_active_user] = lambda: user

    api.someone, api.owner_as, api.act_as = someone, owner_as, act_as
    try:
        yield api
    finally:
        async with api.env.factory.begin() as db:
            await db.execute(delete(AuditLog).where(AuditLog.user_id.in_(created)))
            await db.execute(delete(User).where(User.id.in_(created)))


async def auditor_rows(api: SimpleNamespace, user: User) -> list[tuple[str, str, Any]]:
    async with api.env.factory() as db:
        rows = (
            await db.scalars(
                select(AuditLog)
                .where(AuditLog.user_id == user.id, AuditLog.action.like("auditor.%"))
                .order_by(AuditLog.timestamp, AuditLog.id)
            )
        ).all()
    return [(row.action, row.resource_id, row.details) for row in rows]


async def awaiting(api: SimpleNamespace) -> dict[str, Any]:
    """A run of the owner's whose plan is waiting for approval."""
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    assert await job(api, value["root_id"]) == "completed"
    planned = await read(api, value["root_id"])
    assert planned["status"] == "awaiting_approval"
    return planned


def approval(planned: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": planned["tree"]["plan"]["revision"],
        "plan_hash": planned["tree"]["plan_hash"],
    }


# --- A read-only role cannot act ----------------------------------------------


@pytest.mark.parametrize("role", ["viewer", "auditor"])
async def test_a_read_only_role_cannot_start_a_run_and_is_told_why(
    roles: SimpleNamespace, role: str
) -> None:
    api = roles
    chat_id = await new_chat(api)
    await api.owner_as(role)

    profiles = (await api.client.get(f"{CHATS}/{chat_id}/run-profiles")).json()
    harness = next(p for p in profiles["profiles"] if p["profile"] == PROFILE)
    assert (harness["available"], harness["reason"]) == (False, "role_read_only")
    assert harness["reason_text"] == "Your role has read-only access, so you cannot start a run."

    response = await api.client.post(
        f"{CHATS}/{chat_id}/runs",
        json={"request_id": str(uuid4()), "profile": PROFILE, "goal": GOAL},
    )
    assert response.status_code == 403, response.text
    assert READ_ONLY in response.text
    # The retained stand-alone route has the same gate.
    legacy = await api.client.post(
        f"{BASE}/chat-runs",
        json={"request_id": str(uuid4()), "project_id": str(api.env.project_id), "goal": GOAL},
    )
    assert legacy.status_code == 403 and READ_ONLY in legacy.text
    async with api.env.factory() as db:
        assert not (
            await db.scalars(
                select(OrchestrationRoot.session_id).where(
                    OrchestrationRoot.owner_id == api.env.owner_id,
                    OrchestrationRoot.profile == PROFILE,
                )
            )
        ).all()
    assert api.gateway.requests == []


async def test_the_store_refuses_a_read_only_role_where_no_route_stands_in_front(
    roles: SimpleNamespace,
) -> None:
    """The rule is held where a run is created and approved, not only at the route."""
    api = roles
    planned = await awaiting(api)
    root_id = UUID(planned["root_id"])
    viewer = await api.owner_as("viewer")

    with pytest.raises(Forbidden, match=r"requires .write. access to the matter"):
        await api.runtime.store.approve(root_id, actor_id=viewer.id, **approval(planned))
    with pytest.raises(Forbidden, match=r"requires .write. access to the matter"):
        await api.runtime.store.reject(
            root_id, actor_id=viewer.id, revision=planned["tree"]["plan"]["revision"]
        )
    assert (await read(api, planned["root_id"]))["status"] == "awaiting_approval"
    # Halt the first so that only the role stands between the viewer and a new run.
    assert (await api.client.post(f"{BASE}/chat-runs/{root_id}/halt")).status_code == 200
    with pytest.raises(Forbidden, match=r"requires .write. access to the matter"):
        await begin_run(
            api.runtime.for_profile(PROFILE),
            user=viewer,
            request_id=uuid4(),
            project_id=api.env.project_id,
            goal=GOAL,
            chat_id=await new_chat(api),
        )


async def test_an_owner_made_a_viewer_reads_and_halts_their_run_but_cannot_approve_or_reject(
    roles: SimpleNamespace,
) -> None:
    api = roles
    planned = await awaiting(api)
    root = planned["root_id"]
    await api.owner_as("viewer")

    approved = await api.client.post(f"{BASE}/{root}/approve", json=approval(planned))
    assert approved.status_code == 403 and READ_ONLY in approved.text
    rejected = await api.client.post(
        f"{BASE}/{root}/reject", json={"revision": planned["tree"]["plan"]["revision"]}
    )
    assert rejected.status_code == 403 and READ_ONLY in rejected.text

    # Reading their own run is unchanged, and writes no auditor row.
    assert (await read(api, root))["status"] == "awaiting_approval"
    assert (await api.client.get(f"{BASE}/{root}/tree")).status_code == 200
    assert (await api.client.get(f"{BASE}/{root}/sessions/{root}/trace")).status_code == 200
    async with api.env.factory() as db:
        assert not (
            await db.scalars(
                select(AuditLog.id).where(
                    AuditLog.user_id == api.env.owner_id, AuditLog.action.like("auditor.%")
                )
            )
        ).all()

    # Halting only narrows authority, so a changed role does not take it away.
    halted = await api.client.post(f"{BASE}/chat-runs/{root}/halt")
    assert halted.status_code == 200 and halted.json()["status"] == "halted"


async def test_closing_and_the_tree_halt_stay_reachable_for_an_owner_made_a_viewer(
    roles: SimpleNamespace,
) -> None:
    """Both only narrow authority, so a changed role does not take them away.

    Close answers for the run's state (this run is not uncertain), never for the role:
    moving it behind the gate would make it a 403 and leave such an owner unable to
    release an uncertain run.
    """
    api = roles
    planned = await awaiting(api)
    root = planned["root_id"]
    await api.owner_as("viewer")

    closed = await api.client.post(f"{BASE}/chat-runs/{root}/close")
    assert closed.status_code == 409 and READ_ONLY not in closed.text
    halted = await api.client.post(f"{BASE}/{root}/halt")
    assert halted.status_code == 200, halted.text
    assert halted.json()["status"] == "halted"


async def test_a_member_again_can_approve(roles: SimpleNamespace) -> None:
    """The gate reads the role as it is now, in both directions."""
    api = roles
    planned = await awaiting(api)
    await api.owner_as("viewer")
    refused = await api.client.post(f"{BASE}/{planned['root_id']}/approve", json=approval(planned))
    assert refused.status_code == 403
    await api.owner_as("member")
    accepted = await api.client.post(f"{BASE}/{planned['root_id']}/approve", json=approval(planned))
    assert accepted.status_code == 200, accepted.text


# --- An admin or an auditor reads another owner's run -------------------------


@pytest.mark.parametrize(("role", "admin"), [("auditor", False), ("admin", True)])
async def test_a_privileged_reader_reads_another_owners_run_and_each_read_is_audited(
    roles: SimpleNamespace, role: str, admin: bool
) -> None:
    api = roles
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    done = await run_to_completion(api, value)
    root = value["root_id"]
    child = done["tree"]["plan"]["children"][0]["dispatch_id"]
    # Every task keeps its findings as a working file, which its owner can read.
    owner_file = await api.client.get(f"{BASE}/{root}/files/{child}/findings.json")
    assert owner_file.status_code == 200 and owner_file.json()["content"]

    reader = await api.someone(role, admin=admin, matter_read=True)
    api.act_as(reader)

    run = await api.client.get(f"{BASE}/chat-runs/{root}")
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "completed" and run.json()["planning"]["goal"] == GOAL
    tree = await api.client.get(f"{BASE}/{root}/tree")
    assert tree.status_code == 200 and tree.json()["plan"]["goal"] == GOAL
    for session in (root, child):
        trace = await api.client.get(f"{BASE}/{root}/sessions/{session}/trace")
        assert trace.status_code == 200, trace.text
        assert trace.json()["calls"], "the trace shows how the session's calls were set up"

    viewed = {"viewed_user_id": str(api.env.owner_id)}
    assert await auditor_rows(api, reader) == [
        ("auditor.run_viewed", root, viewed),
        ("auditor.run_viewed", root, viewed),
        ("auditor.run_trace_viewed", root, viewed),
        ("auditor.run_trace_viewed", root, viewed),
    ]

    # Reads only. The working-file route refuses them, and nothing can be done to the run.
    assert (await api.client.get(f"{BASE}/{root}/files/{child}/findings.json")).status_code == 404
    assert (await api.client.post(f"{BASE}/chat-runs/{root}/halt")).status_code == 404
    assert (await api.client.post(f"{BASE}/chat-runs/{root}/close")).status_code == 404
    assert (await api.client.post(f"{BASE}/{root}/halt")).status_code == 404
    # Refused reads and actions write no further auditor rows.
    assert len(await auditor_rows(api, reader)) == 4


async def test_the_owner_sees_in_the_receipts_who_read_their_run(roles: SimpleNamespace) -> None:
    """A privileged read is an event in the owner's own feed, with the reader's id.

    The reader's `auditor.run_viewed` row is keyed to the run's session, which the
    feed resolves through the chat's run message. Whether an owner should see this
    was not recorded before; this pins what is built: they do, as they see
    `receipts_viewed` rows for their chat (audit the auditor).
    """
    api = roles
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    await run_to_completion(api, value)
    reader = await api.someone("auditor", matter_read=True)
    api.act_as(reader)
    assert (await api.client.get(f"{BASE}/chat-runs/{value['root_id']}")).status_code == 200

    await api.owner_as("member")
    response = await api.client.get(f"{CHATS}/{value['chat_id']}/receipts")
    assert response.status_code == 200, response.text
    seen = [
        (e["detail"]["action"], e["detail"]["actor_user_id"], e["detail"]["run_root_id"])
        for e in response.json()
        if e["kind"] == "audit" and e["detail"]["action"].startswith("auditor.")
    ]
    assert seen == [("auditor.run_viewed", str(reader.id), value["root_id"])]


@pytest.mark.parametrize(("role", "admin"), [("auditor", False), ("admin", True)])
async def test_a_privileged_reader_cannot_approve_or_reject_another_owners_plan(
    roles: SimpleNamespace, role: str, admin: bool
) -> None:
    api = roles
    planned = await awaiting(api)
    root = planned["root_id"]
    reader = await api.someone(role, admin=admin)
    api.act_as(reader)

    approved = await api.client.post(f"{BASE}/{root}/approve", json=approval(planned))
    rejected = await api.client.post(
        f"{BASE}/{root}/reject", json={"revision": planned["tree"]["plan"]["revision"]}
    )
    # An auditor is refused for the role; an admin, who may act on their own runs,
    # is told the run does not exist for them.
    expected = 404 if admin else 403
    assert (approved.status_code, rejected.status_code) == (expected, expected)

    api.act_as(api.user)
    assert (await read(api, root))["status"] == "awaiting_approval"


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_anyone_else_gets_the_404_of_a_missing_run_and_no_audit_row(
    roles: SimpleNamespace, role: str
) -> None:
    api = roles
    planned = await awaiting(api)
    root = planned["root_id"]
    stranger = await api.someone(role)
    api.act_as(stranger)

    missing = str(uuid4())
    for target in (root, missing):
        responses = [
            await api.client.get(f"{BASE}/chat-runs/{target}"),
            await api.client.get(f"{BASE}/{target}/tree"),
            await api.client.get(f"{BASE}/{target}/sessions/{target}/trace"),
        ]
        assert [r.status_code for r in responses] == [404, 404, 404]
    # The same body for a run that exists and one that does not.
    for path in ("chat-runs/{}", "{}/tree", "{0}/sessions/{0}/trace"):
        there = await api.client.get(f"{BASE}/{path.format(root)}")
        absent = await api.client.get(f"{BASE}/{path.format(missing)}")
        assert there.json() == absent.json()
    assert await auditor_rows(api, stranger) == []


async def test_a_privileged_reader_asking_for_a_run_that_does_not_exist_writes_no_row(
    roles: SimpleNamespace,
) -> None:
    api = roles
    auditor = await api.someone("auditor")
    api.act_as(auditor)

    missing = str(uuid4())
    assert (await api.client.get(f"{BASE}/chat-runs/{missing}")).status_code == 404
    assert (await api.client.get(f"{BASE}/{missing}/tree")).status_code == 404
    assert (await api.client.get(f"{BASE}/{missing}/sessions/{missing}/trace")).status_code == 404
    assert await auditor_rows(api, auditor) == []


async def test_what_a_privileged_reader_sees_of_a_tasks_work_without_the_file_route(
    roles: SimpleNamespace,
) -> None:
    """Found in review. The working-file route is owner-only; the content is not.

    A task's findings are its outcome in the tree, and the text of a note is
    the arguments of the call that saved it, which the trace shows. A privileged
    reader is given the tree and the trace, so they read both. This test states
    that as it is. If a note's text should not reach them, the trace has to
    leave it out; refusing the file route does not do it.
    """
    api = roles
    api.gateway.child_script = [
        [
            tool_call(
                "save_note",
                {"name": "note-fees.md", "content": "NOTE-TEXT: fees are due.", "reason": "Keep."},
            )
        ],
        None,
    ]
    api.gateway.child_answer = "FINDINGS-TEXT: fees are due in thirty days."
    value = await start_in_chat(api, await new_chat(api), profile=PROFILE)
    done = await run_to_completion(api, value)
    root = value["root_id"]
    child = done["tree"]["plan"]["children"][0]["dispatch_id"]
    # The owner's own files hold exactly these two texts.
    note = await api.client.get(f"{BASE}/{root}/files/{child}/note-fees.md")
    findings = await api.client.get(f"{BASE}/{root}/files/{child}/findings.json")
    assert note.status_code == 200 and note.json()["content"] == "NOTE-TEXT: fees are due."
    assert findings.status_code == 200 and "FINDINGS-TEXT" in findings.json()["content"]

    api.act_as(await api.someone("auditor", matter_read=True))
    for name in ("note-fees.md", "findings.json"):
        assert (await api.client.get(f"{BASE}/{root}/files/{child}/{name}")).status_code == 404
    tree = await api.client.get(f"{BASE}/{root}/tree")
    trace = await api.client.get(f"{BASE}/{root}/sessions/{child}/trace")
    assert tree.status_code == 200 and trace.status_code == 200
    assert "FINDINGS-TEXT" in tree.text
    assert "NOTE-TEXT: fees are due." in trace.text


@pytest.mark.parametrize(("role", "admin"), [("auditor", False), ("admin", True)])
@pytest.mark.parametrize("screened", [False, True])
async def test_privileged_run_reads_require_actual_callers_matter_access(
    roles: SimpleNamespace, role: str, admin: bool, screened: bool
) -> None:
    api = roles
    planned = await awaiting(api)
    root = planned["root_id"]
    reader = await api.someone(role, admin=admin)
    if screened:
        async with api.env.factory.begin() as db:
            db.add(ProjectMember(project_id=api.env.project_id, user_id=reader.id, role="blocked"))
    api.act_as(reader)
    for path in (f"chat-runs/{root}", f"{root}/tree", f"{root}/sessions/{root}/trace"):
        response = await api.client.get(f"{BASE}/{path}")
        assert response.status_code == 404, response.text
    assert await auditor_rows(api, reader) == []


async def test_screened_owner_cannot_use_chat_run_composer_or_retained_results(
    roles: SimpleNamespace,
) -> None:
    api = roles
    planned = await awaiting(api)
    root = planned["root_id"]
    async with api.env.factory.begin() as db:
        db.add(
            ProjectMember(project_id=api.env.project_id, user_id=api.env.owner_id, role="blocked")
        )
    for path in (
        f"{CHATS}/{planned['chat_id']}/run-profiles",
        f"{CHATS}/{planned['chat_id']}/run-documents",
        f"{CHATS}/{planned['chat_id']}/messages",
        f"{CHATS}/{planned['chat_id']}/receipts",
        f"{BASE}/chat-runs/{root}",
    ):
        response = await api.client.get(path)
        assert response.status_code == 404, response.text


async def test_moving_a_chat_does_not_release_its_retained_run_matter(
    roles: SimpleNamespace,
) -> None:
    from app.api.chats import _load_visible_chat

    api = roles
    planned = await awaiting(api)
    chat_id = UUID(planned["chat_id"])
    async with api.env.factory.begin() as db:
        await db.execute(update(Chat).where(Chat.id == chat_id).values(project_id=None))
        db.add(
            ProjectMember(project_id=api.env.project_id, user_id=api.env.owner_id, role="blocked")
        )
    for suffix in ("messages", "receipts", "run-profiles", "run-documents"):
        response = await api.client.get(f"{CHATS}/{chat_id}/{suffix}")
        assert response.status_code == 404, response.text
    # The write/replay loader must refuse before any retained text reaches a model.
    async with api.env.factory() as db:
        with pytest.raises(NotFound):
            await _load_visible_chat(db, chat_id, api.env.owner_id)
