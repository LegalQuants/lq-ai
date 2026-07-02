"""Skill-registry bootstrap shared by every process that resolves skills.

Why this is a shared helper and not lifespan-inline code
--------------------------------------------------------

The autonomous executor resolves ``skill_ref`` targets through
``app.state.skill_registry`` (see
:func:`app.autonomous.prompts._registry_from_app_state`) in **whatever
process it runs** — the FastAPI api process *or* the arq worker
(scheduled ticks, watches, Run-now all execute
``autonomous_session_job`` on the worker). Both startup paths must
therefore install the registry on the imported ``app`` object's state.

Historically only the FastAPI lifespan (``app/main.py``) did, so every
worker-side ``skill_ref`` session died at the analysis phase with
``ValueError: assemble_analysis_messages: skill registry not
initialised`` — playbook sources were unaffected because they resolve
from the DB. Extracting the bootstrap here lets
:func:`app.workers.arq_setup.on_startup` install the same registry the
api installs, from the same settings, with the same directory-resolution
rules.

What stays out of this helper
-----------------------------

:func:`app.skills.install_sighup_reload` is **not** called here — signal
handlers are api-process policy (the SIGHUP reload contract is
documented for the api container). ``main.py`` keeps installing it on
the holder this helper returns. Consequence of that asymmetry: a SIGHUP
reload of the api does **not** refresh a running worker's snapshot —
the worker loads its registry once at startup, so corpus changes reach
the worker only via a worker restart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.config import Settings

log = logging.getLogger(__name__)


def resolve_skill_dirs(settings: Settings) -> tuple[Path, Path | None]:
    """Resolve the built-in and community skills directories from settings.

    Mirrors the resolution rules documented on the settings fields
    (Task C1 / ADR 0004), moved verbatim from the api lifespan:

    * ``skills_dir`` resolves against the process working directory if
      relative.
    * ``community_skills_dir``, when unset, defaults to the community
      submodule location ``<skills_dir>/community/skills/``.
    * The community dir is only returned when it actually exists, so
      startup does not warn loudly on fresh clones that omitted
      ``--recurse-submodules``.
    """
    skills_dir = Path(settings.skills_dir).resolve()
    if settings.community_skills_dir:
        community_skills_dir: Path | None = Path(settings.community_skills_dir).resolve()
    else:
        # Default: community submodule lives at skills/community/skills/ inside
        # the repo root. skills_dir is the repo's skills/ directory, so the
        # community path is skills_dir / community / skills.
        candidate = skills_dir / "community" / "skills"
        community_skills_dir = candidate if candidate.is_dir() else None
    # Only pass community dir when it actually exists so startup does not
    # warn loudly on fresh clones that omitted --recurse-submodules.
    effective_community_dir = (
        community_skills_dir
        if community_skills_dir is not None and community_skills_dir.is_dir()
        else None
    )
    return skills_dir, effective_community_dir


def install_skill_registry(
    app: FastAPI,
    settings: Settings,
    *,
    resolved_dirs: tuple[Path, Path | None] | None = None,
) -> MutableSkillRegistry:
    """Build the skill registry and install it at ``app.state.skill_registry``.

    Walks the configured skills directory and the community submodule
    directory (per :func:`resolve_skill_dirs`), parses + validates each
    SKILL.md's frontmatter, and registers in memory. Built-in skills win
    on slug collision with community skills. Per-skill failures emit
    WARNING and are skipped; the registry is built from whatever parses
    cleanly (see :func:`app.skills.loader.load_registry`).

    Args:
        app: The FastAPI app whose ``state`` receives the registry.
        settings: Backend settings; used to resolve the skill dirs when
            ``resolved_dirs`` is not supplied.
        resolved_dirs: Optional pre-computed ``resolve_skill_dirs(settings)``
            result, so callers that also need the dirs (the api lifespan
            wires SIGHUP reload onto them) resolve exactly once.

    Raises:
        FileNotFoundError: If the configured ``skills_dir`` does not
            exist or is not a directory. A process that cannot see the
            skill corpus cannot resolve any ``skill_ref`` — failing
            loudly at startup beats serving an empty registry and dying
            at the first skill resolution (e.g., the worker's first
            scheduled 9 AM tick).

    Returns:
        The installed :class:`MutableSkillRegistry` holder, so callers
        (the api lifespan) can wire follow-on policy such as
        :func:`app.skills.install_sighup_reload` onto it.
    """
    skills_dir, effective_community_dir = (
        resolved_dirs if resolved_dirs is not None else resolve_skill_dirs(settings)
    )
    if not skills_dir.is_dir():
        raise FileNotFoundError(
            f"skills directory does not exist or is not a directory: {skills_dir} "
            "(set SKILLS_DIR to the skill corpus location)"
        )
    initial_registry = load_registry(skills_dir, community_skills_dir=effective_community_dir)
    holder = MutableSkillRegistry(initial_registry)
    app.state.skill_registry = holder
    return holder


__all__ = ["install_skill_registry", "resolve_skill_dirs"]
