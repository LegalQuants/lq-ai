"""Skill loading + registry — backend-side per ADR 0004.

Public surface:

* :class:`SkillRegistry` — in-memory registry with atomic-swap reload.
* :func:`load_registry` — walk a skills directory, build a fresh registry.
* :func:`install_sighup_reload` — wire the registry to SIGHUP for in-place
  reloads on a running process.
* :func:`install_skill_registry` / :func:`resolve_skill_dirs` — shared
  bootstrap that builds the registry from settings and installs it at
  ``app.state.skill_registry``; called from BOTH the FastAPI lifespan and
  the arq worker's ``on_startup`` (see :mod:`app.skills.bootstrap`).

The Pydantic schema for the frontmatter (the ``lq_ai:`` namespace) lives
in :mod:`app.skills.schema`; the wire shapes returned to API clients are
defined alongside it and match ``SkillSummary`` / ``Skill`` in
``docs/api/backend-openapi.yaml``.

Design notes:

* The loader is **permissive** about which fields appear in the
  frontmatter — the M1 starter skills predate the formal authoring
  guide and don't all conform (e.g., ``output_format: markdown`` rather
  than ``report``; ``jurisdiction: agnostic`` rather than ``global``;
  some skills have no ``lq_ai:`` namespace at all). Strict-mode
  validation would reject most of the corpus and is not what this loader
  is for. See ADR 0004 and the skill-authoring-guide for the
  forward-looking convention; the loader treats the guide as a
  recommendation, not an enforced contract.
* Per-skill validation failures emit a ``WARNING`` log and skip that
  skill; the rest of the registry builds. Operators see all errors at
  once on startup so they can fix the corpus in one pass rather than
  whack-a-mole.
* Reference and example file *contents* are read lazily — only when
  ``GET /api/v1/skills/{name}`` materialises the full skill — to keep
  startup fast on large skill libraries.
"""

from __future__ import annotations

from app.skills.bootstrap import install_skill_registry, resolve_skill_dirs
from app.skills.loader import LoaderError, install_sighup_reload, load_registry
from app.skills.registry import SkillRegistry
from app.skills.schema import (
    LQAIFrontmatter,
    Skill,
    SkillFile,
    SkillFrontmatter,
    SkillSummary,
)

__all__ = [
    "LQAIFrontmatter",
    "LoaderError",
    "Skill",
    "SkillFile",
    "SkillFrontmatter",
    "SkillRegistry",
    "SkillSummary",
    "install_sighup_reload",
    "install_skill_registry",
    "load_registry",
    "resolve_skill_dirs",
]
