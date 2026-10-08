"""Record real API responses as fixtures for the web client's run components.

Skipped unless ``LQ_DUMP_RUN_FIXTURES`` names a directory. The web client's
helper tests read these files, so the components are tested against what the
API returns and not against a hand-written guess. Regenerate after changing a
run view::

    LQ_DUMP_RUN_FIXTURES=../web/src/lib/lq-ai/run/__fixtures__ \\
      pytest tests/autonomous/orchestration/test_zz_dump_web_fixtures.py

Identifiers and timestamps differ between recordings; nothing in the client's
tests may depend on a particular one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import update
from tests.autonomous.orchestration.model_harness import (
    BASE,
    CHATS,
    approve,
    job,
    messages,
    new_chat,
    read,
    run_to_completion,
    start_in_chat,
    tool_call,
)

from app.api.dependencies import get_admin_user
from app.main import app
from app.models.document import Document
from app.models.file import File
from app.models.orchestration import OrchestrationAccount as Account
from app.models.project import ProjectFile

TARGET = os.environ.get("LQ_DUMP_RUN_FIXTURES")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TARGET, reason="set LQ_DUMP_RUN_FIXTURES to record web fixtures"),
]


def save(name: str, value: Any) -> None:
    assert TARGET
    folder = Path(TARGET)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


async def get(api: SimpleNamespace, path: str, **params: Any) -> Any:
    response = await api.client.get(path, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


async def add_file(
    api: SimpleNamespace,
    filename: str,
    text: str | None,
    *,
    mime: str = "text/plain",
    attached: bool = True,
    status: str = "ready",
) -> str:
    async with api.env.factory.begin() as db:
        file = File(
            owner_id=api.env.owner_id,
            project_id=api.env.project_id,
            filename=filename,
            mime_type=mime,
            size_bytes=len((text or "").encode()) or 1,
            hash_sha256="0" * 64,
            storage_path=str(uuid4()),
            ingestion_status=status,
        )
        db.add(file)
        await db.flush()
        if text is not None:
            db.add(
                Document(
                    file_id=file.id,
                    parser="fixture",
                    character_count=len(text),
                    normalized_content=text,
                )
            )
        if attached:
            db.add(ProjectFile(project_id=api.env.project_id, file_id=file.id))
        return str(file.id)


async def test_record_the_fictional_profile_in_a_chat(model_demo: SimpleNamespace) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    save("profiles.available", await get(api, f"{CHATS}/{chat_id}/run-profiles"))
    no_project = await new_chat(api, in_project=False)
    save("profiles.no-project", await get(api, f"{CHATS}/{no_project}/run-profiles"))

    value = await start_in_chat(api, chat_id)
    root = value["root_id"]
    save("run.planning", value)
    save("thread.planning", await messages(api, chat_id))
    other = await new_chat(api, title="Another chat")
    save("profiles.active-run", await get(api, f"{CHATS}/{other}/run-profiles"))

    assert await job(api, root) == "completed"
    planned = await read(api, root)
    save("run.awaiting-approval", planned)
    await approve(api, planned)
    save("run.queued", await read(api, root))
    assert await job(api, root) == "waiting_children"
    save("run.children-admitted", await read(api, root))
    first, second = (c["dispatch_id"] for c in planned["tree"]["plan"]["children"])
    assert await job(api, root, first) == "completed"
    save("run.one-child-done", await read(api, root))
    assert await job(api, root, second) == "completed"
    assert await job(api, root) == "completed"
    final = await read(api, root)
    save("run.completed", final)
    save("thread.completed", await messages(api, chat_id))
    save("receipts.completed", await get(api, f"{CHATS}/{chat_id}/receipts"))
    child = final["tree"]["children"][0]
    save(
        "file.findings",
        await get(api, f"{BASE}/{root}/files/{child['session_id']}/findings.json"),
    )


async def test_record_stopped_runs(model_demo: SimpleNamespace) -> None:
    api = model_demo
    chat_id = await new_chat(api)

    rejected = await start_in_chat(api, chat_id, goal="A request whose plan is rejected.")
    assert await job(api, rejected["root_id"]) == "completed"
    response = await api.client.post(f"{BASE}/{rejected['root_id']}/reject", json={"revision": 1})
    assert response.status_code == 200
    save("run.rejected", await read(api, rejected["root_id"]))

    halted = await start_in_chat(api, chat_id, goal="A request halted while children run.")
    root = halted["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    first = planned["tree"]["plan"]["children"][0]["dispatch_id"]
    assert await job(api, root, first) == "completed"
    assert (await api.client.post(f"{BASE}/chat-runs/{root}/halt")).status_code == 200
    save("run.halted", await read(api, root))

    api.gateway.proposal = "not json"
    failed = await start_in_chat(api, chat_id, goal="A request the model cannot plan.")
    assert await job(api, failed["root_id"]) == "completed"
    save("run.failed-plan", await read(api, failed["root_id"]))

    tasks = [
        {
            "topic": f"Task {n}",
            "question": "A question?",
            "boundaries": "Only the agreement",
            "output_contract": "An answer",
            "stopping_condition": "One answer",
        }
        for n in range(1, 4)
    ]
    api.gateway.proposal = json.dumps({"tasks": tasks})
    unfunded = await start_in_chat(api, chat_id, goal="A request planned into too many tasks.")
    assert await job(api, unfunded["root_id"]) == "completed"
    save("run.unfunded-plan", await read(api, unfunded["root_id"]))
    save("thread.stopped", await messages(api, chat_id))


async def test_record_uncertain_and_closed_runs(model_demo: SimpleNamespace) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    api.gateway.uncertain = True
    stuck = await start_in_chat(api, chat_id, goal="A request whose planning call times out.")
    await job(api, stuck["root_id"])
    save("run.uncertain-planning", await read(api, stuck["root_id"]))
    save("profiles.uncertain-run", await get(api, f"{CHATS}/{chat_id}/run-profiles"))
    closed = await api.client.post(f"{BASE}/chat-runs/{stuck['root_id']}/close")
    assert closed.status_code == 200
    save("run.closed-planning", closed.json())

    api.gateway.uncertain = False
    value = await start_in_chat(api, chat_id, goal="A request whose second task times out.")
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    first, second = (c["dispatch_id"] for c in planned["tree"]["plan"]["children"])
    assert await job(api, root, first) == "completed"
    api.gateway.uncertain_operations = {"answer_contract_question"}
    await job(api, root, second)
    save("run.uncertain-child", await read(api, root))
    closed = await api.client.post(f"{BASE}/chat-runs/{root}/close")
    assert closed.status_code == 200
    save("run.closed-child", closed.json())
    save("thread.closed", await messages(api, chat_id))


async def test_record_refusals_and_a_failed_topic(model_demo: SimpleNamespace) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    api.gateway.child_script = [
        [
            tool_call("delete_everything", {"reason": "<img src=x onerror=alert(1)>"}, "call_a"),
            tool_call("read_document", {"document": "one"}, "call_b"),
            tool_call("read_document", {"document": 9, "reason": "A ninth document."}, "call_c"),
            tool_call(
                "save_note",
                {"name": "note-terms.md", "content": "Term: see §5.", "reason": "Keep the term."},
                "call_d",
            ),
            tool_call(
                "read_document",
                {"document": 1, "reason": "<script>alert('hostile')</script> read it"},
                "call_e",
            ),
        ],
        [tool_call("read_note", {"name": "note-terms.md", "reason": "Check the note."}, "call_f")],
    ]
    # Text that looks like markup must be shown as text wherever it appears.
    api.gateway.child_answer = (
        "<b>Renewal</b> needs 30 days' notice. [§5]\n\n"
        "<script>alert('answer')</script> ![x](javascript:alert(1))"
    )
    value = await start_in_chat(
        api, chat_id, goal="A request with refused calls <i>and markup</i>."
    )
    root = value["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    first, second = (c["dispatch_id"] for c in planned["tree"]["plan"]["children"])
    assert await job(api, root, first) == "completed"
    async with api.env.factory.begin() as db:
        from uuid import UUID

        await db.execute(
            update(Account)
            .where(Account.session_id == UUID(second))
            .values(allocation_usd="0.2600")
        )
    assert await job(api, root, second) == "completed"
    assert await job(api, root) == "completed"
    save("run.refusals-and-partial", await read(api, root))
    save("thread.partial", await messages(api, chat_id))


async def test_record_the_real_document_profile(model_demo: SimpleNamespace) -> None:
    api = model_demo
    api.runtime.settings.orchestration_documents_enabled = True
    chat_id = await new_chat(api)
    msa_text = (
        "MASTER SERVICES AGREEMENT\n\n"
        "4. Fees. Customer shall pay the Fees within thirty (30) days of the invoice date.\n"
        "9. Term. This Agreement renews for successive one-year terms unless either party "
        "gives ninety (90) days written notice of non-renewal.\n"
    )
    dpa_text = (
        "DATA PROCESSING ADDENDUM\n\n"
        "3. Breach notice. Processor shall notify Controller without undue delay and in any "
        "event within seventy-two (72) hours of becoming aware of a Personal Data Breach.\n"
    )
    msa = await add_file(api, "msa.txt", msa_text)
    dpa = await add_file(api, "dpa.md", dpa_text, mime="text/markdown", attached=False)
    await add_file(
        api,
        "draft.docx",
        "text",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    await add_file(api, "scan.pdf", None, mime="application/pdf", status="pending")
    await add_file(api, "broken.pdf", None, mime="application/pdf", status="failed")
    await add_file(api, "image-only.pdf", "  ", mime="application/pdf")
    save("profiles.documents", await get(api, f"{CHATS}/{chat_id}/run-profiles"))
    save("documents.list", await get(api, f"{CHATS}/{chat_id}/run-documents", file_id=[dpa]))

    api.gateway.expected_documents = [
        {"number": 1, "filename": "msa.txt"},
        {"number": 2, "filename": "dpa.md"},
    ]
    api.gateway.child_script = [
        [
            tool_call("read_document", {"document": 1, "reason": "Read the MSA."}, "call_a"),
            tool_call("read_document", {"document": 2, "reason": "Read the DPA."}, "call_b"),
        ],
        None,
    ]
    quoted = (
        'Fees are due "within thirty (30) days of the invoice date" (Source: [1]). '
        'Breach notice is due "within seventy-two (72) hours of becoming aware of a '
        'Personal Data Breach" (Source: [2]).'
    )
    api.gateway.child_answer = quoted
    api.gateway.synthesis_answer = (
        "## Payment and breach notice\n\n"
        + quoted
        + ' The liability cap is "twelve months of fees" (Source: [1]).'
    )
    value = await start_in_chat(
        api, chat_id, profile="contract_qa_documents_v1", file_ids=[msa, dpa]
    )
    save("run.documents.planning", value)
    root = value["root_id"]
    assert await job(api, root) == "completed"
    save("run.documents.awaiting-approval", await read(api, root))
    final = await run_documents_to_completion(api, root)
    save("run.documents.completed", final)
    thread = await messages(api, chat_id)
    save("thread.documents.completed", thread)
    message_id = thread[1]["id"]
    save(
        "citations.documents", await get(api, f"{CHATS}/{chat_id}/messages/{message_id}/citations")
    )
    save("ledger.documents", await get(api, f"{CHATS}/{chat_id}/ledger", message_id=message_id))

    app.dependency_overrides[get_admin_user] = lambda: api.user
    try:
        save("admin.profiles", await get(api, "/api/v1/admin/orchestration/profiles"))
    finally:
        app.dependency_overrides.pop(get_admin_user, None)


async def run_documents_to_completion(api: SimpleNamespace, root: str) -> dict[str, Any]:
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    for child in planned["tree"]["plan"]["children"]:
        assert await job(api, root, child["dispatch_id"]) == "completed"
    assert await job(api, root) == "completed"
    return await read(api, root)


async def test_the_recording_helpers_are_used(model_demo: SimpleNamespace) -> None:
    # Keeps run_to_completion imported for recordings that need the short form.
    assert callable(run_to_completion)
