"""Regression — skill_ref resolution through the WORKER startup path.

Donna ask #9: ``skill_ref`` autonomous sessions executed on the arq
worker (scheduled ticks, watches, Run-now all land there) failed at the
analysis phase with ``ValueError: assemble_analysis_messages: skill
registry not initialised`` because only the FastAPI lifespan installed
the registry at ``app.state.skill_registry``; the worker's
``on_startup`` never did.

The exact gap that let this ship: every prior test that exercised
worker-side skill resolution installed the registry via the
``_installed_skill_registry`` conftest fixture — i.e. it replicated the
API's startup, not the worker's. This module deliberately does NOT use
that fixture. It runs :func:`app.workers.arq_setup.on_startup` (the
worker's real boot hook) and asserts that, with ONLY that having run,
prompt assembly for a ``skill_ref`` session resolves the skill.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.prompts import assemble_analysis_messages
from app.config import get_settings
from app.models.autonomous import AutonomousSession
from app.models.user import User
from app.security import hash_password
from app.workers import arq_setup

# Same fixture corpus the C1 internal-skills + autonomous prompt tests
# use; ``alpha-test-skill`` is a known-loaded name.
_SKILL_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"
_FIXTURE_SKILL_REF = "alpha-test-skill"


async def _make_skill_ref_session(db: AsyncSession) -> AutonomousSession:
    """Insert a minimal user + skill_ref session (mirrors conftest helpers).

    Inlined rather than reusing the ``session_with_skill_ref`` fixture
    because that fixture depends on ``_installed_skill_registry`` — the
    API-shaped registry install this test must NOT perform.
    """
    user = User(
        email=f"u-worker-reg-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        params={"skill_ref": _FIXTURE_SKILL_REF},
    )
    db.add(sess)
    await db.flush()
    return sess


@pytest.mark.integration
async def test_worker_on_startup_installs_registry_for_skill_ref_sessions(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``on_startup`` alone must make skill_ref resolution work.

    Points the worker's settings at the fixture skills corpus, runs the
    worker startup hook, and asserts ``assemble_analysis_messages``
    succeeds for a skill_ref session WITHOUT the API lifespan (and
    without the ``_installed_skill_registry`` fixture) having run.
    """
    from app.main import app

    settings = get_settings().model_copy(update={"skills_dir": str(_SKILL_FIXTURES_DIR)})
    monkeypatch.setattr(arq_setup, "get_settings", lambda: settings)

    # Save/restore app.state hygiene — mirror _installed_skill_registry's
    # teardown so the worker-installed registry never leaks into other
    # tests (which must be free to assert their own registry state).
    prior_holder = getattr(app.state, "skill_registry", None)
    if prior_holder is not None:
        # Start from the broken-world precondition: no registry installed.
        delattr(app.state, "skill_registry")
    try:
        # The worker's REAL startup path — the thing the bug proved was
        # never installing the registry.
        await arq_setup.on_startup({})

        sess = await _make_skill_ref_session(db_session)
        msgs = await assemble_analysis_messages(sess, chunks=[], db=db_session)

        # The skill resolved: system prompt is the fixture SKILL.md body
        # (+ the structured-output tail), not a "not initialised" error.
        assert msgs[0]["role"] == "system"
        assert len(msgs[0]["content"]) > 50
    finally:
        if prior_holder is None:
            if hasattr(app.state, "skill_registry"):
                delattr(app.state, "skill_registry")
        else:
            app.state.skill_registry = prior_holder


@pytest.mark.integration
async def test_worker_on_startup_fails_loudly_on_missing_skills_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A worker that cannot load the skill corpus must die at startup.

    Requested operational posture: propagate, so the container
    crash-loops visibly instead of failing at the first scheduled tick.
    """
    from app.main import app

    missing = tmp_path / "does-not-exist"
    settings = get_settings().model_copy(update={"skills_dir": str(missing)})
    monkeypatch.setattr(arq_setup, "get_settings", lambda: settings)

    prior_holder = getattr(app.state, "skill_registry", None)
    if prior_holder is not None:
        delattr(app.state, "skill_registry")
    try:
        with pytest.raises(FileNotFoundError):
            await arq_setup.on_startup({})
        # Nothing half-installed.
        assert getattr(app.state, "skill_registry", None) is None
    finally:
        if prior_holder is None:
            if hasattr(app.state, "skill_registry"):
                delattr(app.state, "skill_registry")
        else:
            app.state.skill_registry = prior_holder
