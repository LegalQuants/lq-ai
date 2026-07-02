"""Unit tests for :mod:`app.skills.bootstrap` (shared registry bootstrap).

The helper is called from BOTH the FastAPI lifespan and the arq
worker's ``on_startup`` (Donna ask #9 — worker-side skill_ref sessions
failed because only the API installed the registry). These tests cover
the helper in isolation; the worker-startup-path integration test lives
in ``tests/autonomous/test_worker_skill_registry.py``.

Each test passes a throwaway ``FastAPI()`` instance, so nothing touches
the production ``app.main.app`` state — no save/restore needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.skills.bootstrap import install_skill_registry, resolve_skill_dirs
from app.skills.registry import MutableSkillRegistry

_SKILL_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"


def _settings_with(skills_dir: Path, community: str | None = None) -> Settings:
    return get_settings().model_copy(
        update={"skills_dir": str(skills_dir), "community_skills_dir": community}
    )


@pytest.mark.unit
def test_install_skill_registry_installs_holder_on_app_state_and_returns_it() -> None:
    app = FastAPI()
    settings = _settings_with(_SKILL_FIXTURES_DIR)

    holder = install_skill_registry(app, settings)

    assert isinstance(holder, MutableSkillRegistry)
    assert app.state.skill_registry is holder
    # The fixture corpus actually loaded (same names test_internal_skills uses).
    assert "alpha-test-skill" in holder.current().names()


@pytest.mark.unit
def test_install_skill_registry_missing_skills_dir_raises(tmp_path: Path) -> None:
    """Fail-loudly contract: a process that cannot see the skill corpus
    must crash at startup, not serve an empty registry and die at the
    first skill resolution."""
    app = FastAPI()
    settings = _settings_with(tmp_path / "nope")

    with pytest.raises(FileNotFoundError):
        install_skill_registry(app, settings)
    # Nothing half-installed on failure.
    assert getattr(app.state, "skill_registry", None) is None


@pytest.mark.unit
def test_resolve_skill_dirs_explicit_community_dir(tmp_path: Path) -> None:
    community = tmp_path / "community-skills"
    community.mkdir()
    settings = _settings_with(_SKILL_FIXTURES_DIR, community=str(community))

    skills_dir, effective = resolve_skill_dirs(settings)

    assert skills_dir == _SKILL_FIXTURES_DIR
    assert effective == community.resolve()


@pytest.mark.unit
def test_resolve_skill_dirs_nonexistent_community_dir_is_none(tmp_path: Path) -> None:
    """Only-pass-when-exists: a configured-but-absent community dir is
    dropped so startup does not warn loudly (fresh clones without
    --recurse-submodules)."""
    settings = _settings_with(_SKILL_FIXTURES_DIR, community=str(tmp_path / "absent"))

    _, effective = resolve_skill_dirs(settings)

    assert effective is None


@pytest.mark.unit
def test_resolve_skill_dirs_default_community_submodule_absent_is_none() -> None:
    """Unset community dir defaults to <skills_dir>/community/skills,
    which does not exist under the fixture corpus → None."""
    settings = _settings_with(_SKILL_FIXTURES_DIR, community=None)

    _, effective = resolve_skill_dirs(settings)

    assert effective is None
