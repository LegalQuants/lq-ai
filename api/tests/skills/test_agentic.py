import json
from uuid import uuid4

from sqlalchemy import select

from app.autonomous.nodes import make_analysis_node
from app.config import get_settings
from app.main import app
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.project import Project
from tests.autonomous.test_agentic_loop import _ScriptedGateway
from tests.skills.test_capabilities import make_user, skill_registry as skill_registry


async def test_background_planner_can_reuse_complete_saved_data(
    db_session, skill_registry, monkeypatch
):
    owner = make_user()
    owner.autonomous_enabled = True
    db_session.add(owner)
    await db_session.flush()
    project = Project(owner_id=owner.id, name="Fixture", slug=f"fixture-{uuid4()}")
    db_session.add(project)
    await db_session.flush()
    session = AutonomousSession(
        user_id=owner.id,
        project_id=project.id,
        trigger_kind="manual",
        params={"skill_ref": "saved-notes-demo", "model": "fixture"},
    )
    db_session.add(session)
    await db_session.flush()
    monkeypatch.setattr(app.state, "skill_registry", skill_registry, raising=False)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", True)
    notes = "Private saved work beyond the old 120-character observation limit. " * 5
    gateway = _ScriptedGateway(
        [
            {
                "next_intent": "skill_workspace_write",
                "args": {"name": "notes.md", "expected_revision": None, "content": notes},
                "rationale": "save notes",
            },
            {
                "next_intent": "skill_workspace_read",
                "args": {"name": "notes.md"},
                "rationale": "reopen notes",
            },
            {"done": True, "rationale": "enough data"},
        ]
    )
    result = await make_analysis_node(db_session, gateway)(
        {
            "session_id": str(session.id),
            "query": "Use the optional workspace",
            "retrieved_chunks": [],
        }
    )
    assert result["analysis_plan_trace"]["steps"] == 2
    assert result["analysis_evidence"] == []
    assert notes in gateway.captured_requests[2].messages[-1].content
    assert notes in gateway.captured_requests[-1].messages[-1].content
    assert notes not in json.dumps(result["analysis_plan_trace"])
    audit = list(await db_session.scalars(select(AuditLog).where(AuditLog.user_id == owner.id)))
    assert notes not in json.dumps([row.details for row in audit])
