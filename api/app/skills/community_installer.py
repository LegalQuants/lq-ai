"""Community skill catalog scan + provenance helpers — DE-263 (ADR 0027).

The admin installer surface (``app/api/community_skills.py``) serves the
community catalog FROM THE LOCAL SUBMODULE checkout at
``skills/community/skills/`` (or the operator's
``LQ_AI_COMMUNITY_SKILLS_DIR`` override) — never a network fetch. That
preserves the backend single-outbound-client invariant
(``tests/test_transparency_invariants.py``) and air-gap compatibility;
``git submodule update --remote skills/community`` is the operator
refresh path. See ``docs/adr/0027-community-skill-catalog-source.md``.

This module is deliberately free of any ``app.api`` import so the
router can import it without a package cycle. It owns:

* :func:`resolve_catalog_dir` — where the catalog lives for this
  deployment (mirrors the startup resolution rules).
* :func:`scan_catalog` — a per-request re-scan of the community corpus
  using the same parser the registry walk uses, plus honest state about
  an absent submodule.
* :func:`resolve_submodule_sha` — the submodule HEAD commit via PURE
  FILE READS of git plumbing (no git subprocess at request time),
  degrading to ``None`` (surfaced as ``"unknown"``) when the plumbing
  is absent — e.g. an uninitialized submodule or a container image
  built without ``.git``.
* :func:`attestation_of` / :func:`install_fields_from_record` — read
  frontmatter-declared attestation (display-only, never synthesized)
  and map a parsed record onto the ``UserSkillCreate`` field set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.skills.loader import scan_skills_folder
from app.skills.registry import SkillRecord
from app.skills.schema import _humanise

if TYPE_CHECKING:
    from app.config import Settings

# The lq-skills repo name — the stable prefix of the ``forked_from``
# provenance ref written at install time (ADR 0027 §2).
FORKED_FROM_PREFIX = "lq-skills"

# A loose or detached-HEAD object id: 40 hex chars (SHA-1) or 64 (SHA-256
# repos). Anything else read out of the plumbing is treated as unknown.
_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")

# Frontmatter keys we accept as an attestation declaration, checked in
# order at the top level and under ``lq_ai:``. Community skills are
# attested at their source repo (lq-skills PR process); we surface what
# the file declares and never assert more (ADR 0027 §5).
_ATTESTATION_KEYS = ("attested_by", "attested-by", "attestation")

# Operator remedy surfaced when the submodule directory is absent/empty.
SUBMODULE_HINT = (
    "Community catalog is empty. If this deployment was cloned without "
    "--recurse-submodules, run `git submodule update --init skills/community` "
    "(and `git submodule update --remote skills/community` to refresh), then "
    "reload this page."
)


@dataclass(frozen=True)
class CommunityCatalog:
    """One re-scan of the community corpus, with honest source state."""

    path: Path
    """Where the scan looked (shown to the operator even when absent)."""

    dir_present: bool
    """Whether ``path`` exists as a directory. ``False`` == submodule
    not checked out; the catalog is empty with an operator hint, not
    an error (ADR 0027 §3)."""

    sha: str | None
    """Submodule HEAD commit, or ``None`` when unresolvable."""

    records: list[SkillRecord] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)
    """Per-skill parse failures, verbatim from the loader — surfaced to
    the admin so broken corpus entries are visible, not hidden."""


def resolve_catalog_dir(settings: Settings) -> Path:
    """Return the community catalog directory for this deployment.

    Mirrors :func:`app.skills.bootstrap.resolve_skill_dirs` — the
    operator override wins; otherwise the submodule default at
    ``<skills_dir>/community/skills``. Unlike the bootstrap helper this
    returns the candidate path even when it does not exist, so the
    admin UI can show the operator *where* the submodule is expected.
    """

    if settings.community_skills_dir:
        return Path(settings.community_skills_dir).resolve()
    return Path(settings.skills_dir).resolve() / "community" / "skills"


def scan_catalog(catalog_dir: Path) -> CommunityCatalog:
    """Re-scan ``catalog_dir`` and return the catalog with source state."""

    dir_present = catalog_dir.is_dir()
    records: list[SkillRecord] = []
    load_errors: list[str] = []
    if dir_present:
        records, load_errors = scan_skills_folder(catalog_dir, source="community")
    return CommunityCatalog(
        path=catalog_dir,
        dir_present=dir_present,
        sha=resolve_submodule_sha(catalog_dir),
        records=records,
        load_errors=load_errors,
    )


# --- Submodule sha resolution (pure file reads) ------------------------------


def resolve_submodule_sha(catalog_dir: Path) -> str | None:
    """Resolve the submodule HEAD commit without invoking git.

    The catalog dir is ``<submodule root>/skills``, so the ``.git``
    entry normally lives one level up; both levels are checked so an
    operator override pointing directly at a repo root also resolves.

    Resolution chain (all plain file reads):

    1. ``.git`` file → ``gitdir: <path>`` pointer (the submodule case)
       or ``.git`` directory (a plain clone mounted as the corpus).
    2. ``<gitdir>/HEAD`` — a detached HEAD is the sha itself (the
       normal submodule state); a symbolic ref is followed into the
       loose ref file, then ``packed-refs``.

    Returns ``None`` when any link in the chain is missing or
    unparseable — callers surface that as ``"unknown"`` rather than
    guessing (ADR 0027 §2).
    """

    for root in (catalog_dir, catalog_dir.parent):
        sha = _sha_from_git_entry(root / ".git")
        if sha is not None:
            return sha
    return None


def _sha_from_git_entry(git_entry: Path) -> str | None:
    """Resolve HEAD for one ``.git`` file-or-directory candidate."""

    try:
        if git_entry.is_file():
            pointer = git_entry.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            gitdir = (git_entry.parent / pointer.removeprefix("gitdir:").strip()).resolve()
        elif git_entry.is_dir():
            gitdir = git_entry
        else:
            return None

        head_path = gitdir / "HEAD"
        if not head_path.is_file():
            return None
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if _OBJECT_ID_RE.match(head):
        return head  # detached HEAD — the usual submodule state

    if head.startswith("ref:"):
        ref_name = head.removeprefix("ref:").strip()
        return _resolve_ref(gitdir, ref_name)
    return None


def _resolve_ref(gitdir: Path, ref_name: str) -> str | None:
    """Resolve a symbolic ref via the loose ref file, then packed-refs."""

    loose = gitdir / ref_name
    try:
        if loose.is_file():
            candidate = loose.read_text(encoding="utf-8").strip()
            return candidate if _OBJECT_ID_RE.match(candidate) else None

        packed = gitdir / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "^")):
                    continue
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1].strip() == ref_name:
                    return parts[0] if _OBJECT_ID_RE.match(parts[0]) else None
    except OSError:
        return None
    return None


# --- Record → install-payload mapping ----------------------------------------


def forked_from_ref(slug: str, sha: str | None) -> str:
    """Provenance string written to ``user_skills.forked_from`` at install.

    ``lq-skills:<slug>@<sha>`` — sha degrades to the literal
    ``"unknown"`` when the plumbing could not be read, honestly
    recording that the pin was unavailable rather than omitting it.
    """

    return f"{FORKED_FROM_PREFIX}:{slug}@{sha or 'unknown'}"


def attestation_of(record: SkillRecord) -> str | None:
    """Frontmatter-declared attestation string, or ``None``.

    Checked at the frontmatter top level first, then under ``lq_ai:``
    (both are ``extra="allow"`` models, so declarations land in
    ``model_extra``). Only a non-empty string counts — the UI renders
    ``None`` as "none declared in SKILL.md", never as attested.
    """

    fm = record.frontmatter
    for container in (fm.model_extra or {}, fm.lq_ai.model_extra or {}):
        for key in _ATTESTATION_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def display_title(record: SkillRecord) -> str:
    """``lq_ai.title`` when declared; humanised slug otherwise."""

    return record.frontmatter.lq_ai.title or _humanise(record.name)


def install_fields_from_record(record: SkillRecord) -> dict[str, Any]:
    """Map a parsed community record onto the ``UserSkillCreate`` field set.

    The router feeds this dict through ``UserSkillCreate`` so a
    community SKILL.md whose parsed fields violate the ADR 0012 bounds
    (over-long description, empty body, …) is rejected with the same
    422s a hand-authored user skill would get.

    ``frontmatter_extra`` mirrors the fork endpoint's mapping
    (jurisdiction / minimum_inference_tier / output_format carry
    through) so the synthesized gateway payload after install is
    shape-identical to the community original.
    """

    lq = record.frontmatter.lq_ai
    frontmatter_extra: dict[str, Any] = {}
    if lq.jurisdiction is not None:
        frontmatter_extra["jurisdiction"] = lq.jurisdiction
    if lq.minimum_inference_tier is not None:
        frontmatter_extra["minimum_inference_tier"] = lq.minimum_inference_tier
    if lq.output_format is not None:
        frontmatter_extra["output_format"] = lq.output_format

    return {
        "slug": record.name,
        "display_name": display_title(record),
        "description": record.frontmatter.description,
        "body": record.body,
        "version": lq.version or "unversioned",
        "tags": list(lq.tags),
        "frontmatter_extra": frontmatter_extra,
        "scope": "user",
    }


__all__ = [
    "FORKED_FROM_PREFIX",
    "SUBMODULE_HINT",
    "CommunityCatalog",
    "attestation_of",
    "display_title",
    "forked_from_ref",
    "install_fields_from_record",
    "resolve_catalog_dir",
    "resolve_submodule_sha",
    "scan_catalog",
]
