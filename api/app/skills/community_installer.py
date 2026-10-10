"""Community skill catalog scan + provenance helpers — DE-263 (ADR 0041).

The admin installer surface (``app/api/community_skills.py``) serves the
community catalog FROM THE LOCAL SUBMODULE checkout at
``skills/community/skills/`` (or the operator's
``LQ_AI_COMMUNITY_SKILLS_DIR`` override) — never a network fetch. That
preserves the backend single-outbound-client invariant
(``tests/test_transparency_invariants.py``) and air-gap compatibility;
``git submodule update --remote skills/community`` is the operator
refresh path. See ``docs/adr/0041-community-skill-catalog-source.md``.

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

import configparser
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from app.skills.loader import scan_skills_folder
from app.skills.registry import SkillRecord
from app.skills.schema import _humanise

if TYPE_CHECKING:
    from app.config import Settings

# A loose or detached-HEAD object id: 40 hex chars (SHA-1) or 64 (SHA-256
# repos). Anything else read out of the plumbing is treated as unknown.
_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")

# Frontmatter keys we accept as an attestation declaration, checked in
# order at the top level and under ``lq_ai:``. These are declarations
# from the source file, not independently verified attestations.
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
    an error (ADR 0041 §3)."""

    sha: str | None
    """Submodule HEAD commit, or ``None`` when unresolvable."""

    repository: str | None = None
    metadata_source: str = "unknown"
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
    repository, revision, metadata_source = source_metadata(catalog_dir)
    return CommunityCatalog(
        path=catalog_dir,
        dir_present=dir_present,
        sha=revision,
        repository=repository,
        metadata_source=metadata_source,
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
    guessing (ADR 0041 §2).
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
    except (OSError, UnicodeError):
        return None

    if _OBJECT_ID_RE.match(head):
        return head  # detached HEAD — the usual submodule state

    if head.startswith("ref:"):
        ref_name = head.removeprefix("ref:").strip()
        return _resolve_ref(gitdir, ref_name)
    return None


def _resolve_ref(gitdir: Path, ref_name: str) -> str | None:
    """Resolve a symbolic ref via the loose ref file, then packed-refs."""

    if not ref_name.startswith("refs/") or ".." in ref_name or "\\" in ref_name:
        return None
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
    except (OSError, UnicodeError):
        return None
    return None


# --- Record → install-payload mapping ----------------------------------------


def forked_from_ref(slug: str, sha: str | None, repository: str | None = None) -> str:
    """Provenance string written to ``user_skills.forked_from`` at install.

    Actual sanitized repository identity plus slug/revision. Unknown source
    metadata remains unknown; it never inherits the default catalog name.
    """

    return f"{repository or 'unknown-source'}:{slug}@{sha or 'unknown'}"


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
    # Preserve runtime controls (inputs, columns, verification, tier floor and
    # capabilities), not just the three presentation fields in the first draft.
    frontmatter_extra: dict[str, Any] = lq.model_dump(
        mode="json", exclude_none=True, exclude_defaults=True
    )
    for key in ("title", "version", "tags", "author"):
        frontmatter_extra.pop(key, None)
    top_level = record.frontmatter.model_dump(mode="json")
    if "inputs" in top_level and "inputs" not in frontmatter_extra:
        frontmatter_extra["inputs"] = top_level["inputs"]

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

# Operator/build metadata is a declaration, not a verified signature.
CATALOG_METADATA_FILE = "lq-catalog-provenance.json"
HASH_CONTRACT = "sha256:canonical-installed-skill-json:v1"


def public_repository_identity(value: object) -> str | None:
    """Strip credentials, query/fragment and controls from a repository URL."""
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        return None
    if "://" not in value and re.match(r"^[^/@]+@[^/:]+:.+$", value):
        _user, rest = value.split("@", 1)
        host, path = rest.split(":", 1)
        value = f"ssh://{host}/{path}"
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http", "ssh", "git"} or not parsed.hostname:
            return None
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        return None


def _git_directory(root: Path) -> Path | None:
    entry = root / ".git"
    try:
        if entry.is_dir():
            return entry
        if entry.is_file():
            pointer = entry.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                gitdir = (root / pointer.removeprefix("gitdir:").strip()).resolve()
                return gitdir if gitdir.is_dir() else None
    except (OSError, UnicodeError):
        pass
    return None


def source_metadata(catalog_dir: Path) -> tuple[str | None, str | None, str]:
    """Read this checkout's origin, or its portable operator/build manifest."""
    for root in (catalog_dir, catalog_dir.parent):
        gitdir = _git_directory(root)
        if gitdir is not None:
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read_string((gitdir / "config").read_text(encoding="utf-8"))
                repository = public_repository_identity(
                    parser.get('remote "origin"', "url", fallback=None)
                )
                return repository, resolve_submodule_sha(catalog_dir), "git-checkout"
            except (OSError, UnicodeError, configparser.Error):
                return None, resolve_submodule_sha(catalog_dir), "git-checkout"
    for root in (catalog_dir, catalog_dir.parent):
        try:
            path = root / CATALOG_METADATA_FILE
            if path.stat().st_size > 8192:
                continue
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                continue
            repository = public_repository_identity(manifest.get("repository"))
            revision = manifest.get("revision")
            if not isinstance(revision, str) or not _OBJECT_ID_RE.fullmatch(revision):
                revision = None
            return repository, revision, "operator-manifest"
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return None, None, "unknown"


def canonical_hash(value: dict[str, Any]) -> str:
    """Sorted-key compact UTF-8 JSON, no NaN/Infinity; versioned by HASH_CONTRACT."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def installation_snapshot(record: SkillRecord, catalog: CommunityCatalog) -> dict[str, Any]:
    """Hash persisted skill fields; separately bind the source reviewed by the admin."""
    content = install_fields_from_record(record)
    content.pop("scope")
    for key in ("display_name", "description", "version"):
        content[key] = content[key].strip()
    source = {
        "repository": catalog.repository,
        "revision": catalog.sha,
        "metadata_source": catalog.metadata_source,
        "revision_content_verified": False,
        "skill_path": source_skill_path(record, catalog),
        "declared_author": record.frontmatter.lq_ai.author,
        "declared_attestation": attestation_of(record),
        "declared_license": license_declaration(record),
    }
    snapshot = {
        "format_version": 1,
        "hash_contract": HASH_CONTRACT,
        "content_hash": canonical_hash(content),
        "installed_content": content,
        "source": source,
    }
    snapshot["review_hash"] = canonical_hash({"snapshot": snapshot, "raw_yaml": record.raw_yaml})
    return snapshot


def license_declaration(record: SkillRecord) -> str | None:
    value = (record.frontmatter.model_extra or {}).get("license")
    return value if isinstance(value, str) else None


def source_skill_path(record: SkillRecord, catalog: CommunityCatalog) -> str:
    for root in (catalog.path, catalog.path.parent):
        if _git_directory(root) is not None or (root / CATALOG_METADATA_FILE).is_file():
            return (record.folder / "SKILL.md").resolve().relative_to(root.resolve()).as_posix()
    # No repository root is known; this is catalog-relative, not a guessed repo path.
    return f"{record.name}/SKILL.md"
