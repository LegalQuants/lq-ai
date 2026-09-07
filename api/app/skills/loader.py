"""Filesystem walk + frontmatter parse + registry construction.

Public surface:

* :func:`load_registry` — walk a built-in skills directory and an
  optional community skills directory, parse each ``SKILL.md``, and
  build a :class:`SkillRegistry`. Built-in skills win on slug collision
  with community skills; duplicate community slugs are logged and
  skipped.
* :func:`install_sighup_reload` — register a SIGHUP handler that
  rebuilds the registry atomically when the operator signals the
  process.

Per ADR 0004 (skill-loader locus), the loader lives in the backend.
The walk runs synchronously inside the FastAPI lifespan startup — the
filesystem I/O is small and bounded (the M1 corpus is ~10 built-in +
dozens of community skills, each a few KB of frontmatter + body), and
putting it on a thread pool would add complexity without measurable
benefit.
"""

from __future__ import annotations

import logging
import re
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import yaml
from pydantic import ValidationError

from app.skills.registry import MutableSkillRegistry, SkillRecord, SkillRegistry
from app.skills.schema import SkillFrontmatter, SkillSource

log = logging.getLogger(__name__)

# Frontmatter is delimited by lines containing only `---`. The first
# delimiter must be the very first line of the file (no UTF-8 BOM, no
# leading whitespace). The second delimiter terminates the YAML block
# and may appear several lines down.
_FRONTMATTER_RE: Final = re.compile(
    r"\A---\s*\r?\n(?P<yaml>.*?)\r?\n---\s*\r?\n(?P<body>.*)\Z",
    re.DOTALL,
)

# File names treated specially when scanning a skill folder.
_SKILL_FILE_NAME = "SKILL.md"
_REFERENCE_DIR = "reference"
_EXAMPLES_DIR = "examples"

# Files / folders that are not part of a skill at all and must be skipped
# even when present at the top level of the skills directory.
_TOP_LEVEL_NON_SKILLS: Final[frozenset[str]] = frozenset(
    {
        "CONTRIBUTING.md",
        "README.md",
        ".gitignore",
        ".DS_Store",
    }
)


class LoaderError(Exception):
    """Raised when a single skill cannot be parsed.

    The loader catches and logs these per-skill — they do NOT bubble up
    out of :func:`load_registry`. Operators see the WARNING line; the
    skill is omitted from the registry.
    """

    def __init__(self, skill_name: str, message: str) -> None:
        super().__init__(f"{skill_name}: {message}")
        self.skill_name = skill_name


def load_registry(
    skills_dir: Path | str,
    community_skills_dir: Path | str | None = None,
) -> SkillRegistry:
    """Walk ``skills_dir`` (and optionally ``community_skills_dir``) and
    build a :class:`SkillRegistry`.

    Two-pass walk:

    1. Built-in skills from ``skills_dir`` — these are loaded first and
       win unconditionally on slug collision. Each record gets
       ``source="built-in"``.
    2. Community skills from ``community_skills_dir`` (the lq-skills
       submodule at ``skills/community/skills/``) — loaded second. Any
       slug already present from pass 1 is skipped with a single INFO
       log so operators can confirm the dedup is working. Each record
       that makes it in gets ``source="community"``.

    Returns an empty registry if ``skills_dir`` does not exist or
    contains no parseable skills (with a WARNING in either case).
    Per-skill failures emit a WARNING and are skipped; the rest of the
    registry still builds.

    The function is synchronous — fast bounded I/O during startup is
    fine; threadpool offload would add complexity without value.
    """

    records: dict[str, SkillRecord] = {}
    failures: list[str] = []

    # --- Pass 1: built-in skills --------------------------------------------
    base = Path(skills_dir)
    if not base.is_dir():
        log.warning("skills directory does not exist or is not a directory: %s", base)
    else:
        _walk_into(base, source="built-in", records=records, failures=failures, existing=set())

    builtin_count = len(records)

    # --- Pass 2: community skills -------------------------------------------
    community_count = 0
    if community_skills_dir is not None:
        cbase = Path(community_skills_dir)
        if not cbase.is_dir():
            log.warning(
                "community skills directory does not exist or is not a directory: %s",
                cbase,
            )
        else:
            before = len(records)
            _walk_into(
                cbase,
                source="community",
                records=records,
                failures=failures,
                existing=set(records.keys()),
            )
            community_count = len(records) - before

    log.info(
        "skill registry built: %d built-in + %d community skills loaded (from %s and %s)%s",
        builtin_count,
        community_count,
        base,
        community_skills_dir or "none",
        f" ({len(failures)} failures: {failures})" if failures else "",
    )
    return SkillRegistry(records=records)


def _walk_into(
    base: Path,
    *,
    source: SkillSource,
    records: dict[str, SkillRecord],
    failures: list[str],
    existing: set[str],
) -> None:
    """Walk ``base`` and load each skill folder into ``records``.

    Shared by both passes of :func:`load_registry`.

    * ``source`` — the attribution tag to stamp onto each loaded record.
    * ``records`` — mutated in place; new records are added here.
    * ``failures`` — mutated in place; parse errors are appended here.
    * ``existing`` — slug names already present from a prior pass.
      A community slug in ``existing`` is skipped with a single INFO
      log (built-in wins). A within-pass duplicate is logged as WARNING.
    """

    for folder in sorted(_iter_skill_folders(base)):
        # Cross-pass dedup: built-in wins over community.
        if folder.name in existing:
            log.info(
                "community skill %r skipped — a built-in skill with the same "
                "slug already exists (built-in wins on collision)",
                folder.name,
            )
            continue

        try:
            record = _load_one(folder, source=source)
        except LoaderError as exc:
            failures.append(str(exc))
            log.warning("skill load failed: %s", exc)
            continue

        if record.name != folder.name:
            failures.append(
                f"{folder.name}: frontmatter name {record.name!r} does not "
                f"match folder name {folder.name!r}"
            )
            log.warning(
                "skill name/folder mismatch: name=%r folder=%r — skipping",
                record.name,
                folder.name,
            )
            continue

        if record.name in records:
            # Within-pass duplicate (two folders with the same frontmatter
            # name). Sorted iteration ensures deterministic "first wins".
            log.warning(
                "duplicate skill name %r — keeping the first occurrence (%s) "
                "and skipping the duplicate (%s)",
                record.name,
                records[record.name].folder,
                record.folder,
            )
            failures.append(f"{record.name}: duplicate name (skipped)")
            continue

        records[record.name] = record


def _iter_skill_folders(base: Path) -> Iterator[Path]:
    """Yield each top-level subdirectory of ``base`` that *might* be a skill.

    A skill folder is any direct subdirectory whose name is not in the
    documented non-skill set (CONTRIBUTING.md, README.md, etc.) and
    that contains a ``SKILL.md`` file. We don't recurse — skills are
    flat under the skills directory.
    """

    for child in base.iterdir():
        if child.name in _TOP_LEVEL_NON_SKILLS:
            continue
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            # Hidden directories (e.g., .git) are never skills.
            continue
        if not (child / _SKILL_FILE_NAME).is_file():
            continue
        yield child


def _load_one(folder: Path, source: SkillSource = "built-in") -> SkillRecord:
    """Load a single skill from its folder. Raises LoaderError on failure.

    ``source`` is stamped onto the returned :class:`SkillRecord` so the
    API can report attribution (``"built-in"`` vs ``"community"``) without
    inspecting the folder path at query time.
    """

    skill_md = folder / _SKILL_FILE_NAME
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoaderError(folder.name, f"cannot read SKILL.md: {exc}") from exc

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise LoaderError(
            folder.name,
            "SKILL.md is missing the YAML frontmatter delimiters "
            "(expected '---\\n...\\n---\\n' at the top of the file)",
        )

    raw_yaml = match.group("yaml")
    body = match.group("body")

    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise LoaderError(
            folder.name,
            f"frontmatter YAML is invalid: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise LoaderError(
            folder.name,
            f"frontmatter YAML must parse to a mapping (got {type(parsed).__name__})",
        )

    try:
        frontmatter = SkillFrontmatter.model_validate(parsed)
    except ValidationError as exc:
        # Surface the first error message clearly rather than dumping the
        # full Pydantic error object. Operators reading container logs
        # need a one-line "this is what's wrong" signal.
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            msg = first.get("msg", str(exc))
        else:
            loc, msg = "", str(exc)
        raise LoaderError(
            folder.name,
            f"frontmatter validation failed: {loc} — {msg}",
        ) from exc

    reference_paths = _list_subfolder_files(folder / _REFERENCE_DIR)
    example_paths = _list_subfolder_files(folder / _EXAMPLES_DIR)

    return SkillRecord(
        name=frontmatter.name,
        folder=folder,
        frontmatter=frontmatter,
        raw_yaml=raw_yaml,
        body=body,
        source=source,
        reference_paths=tuple(reference_paths),
        example_paths=tuple(example_paths),
    )


def _list_subfolder_files(subfolder: Path) -> list[Path]:
    """List markdown / text files in a skill's reference/ or examples/ dir.

    Returns a sorted list of absolute paths. Subdirectories are walked
    recursively (some skills may organise reference material into
    sub-folders by topic). Non-text files are included so the
    on-disk listing matches what authors put in the folder; the lazy
    file reader handles whatever bytes are there.
    """

    if not subfolder.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(subfolder.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            out.append(path)
    return out


# --- Single-folder scan surface (DE-263 community catalog) -------------------


def scan_skills_folder(
    base: Path | str,
    *,
    source: SkillSource = "community",
) -> tuple[list[SkillRecord], list[str]]:
    """Scan ONE skills folder and return ``(records, failures)``.

    Public wrapper over the same per-folder walk :func:`load_registry`
    uses, for callers that want a raw listing of a single corpus rather
    than the merged registry (the DE-263 community-catalog admin surface
    scans ``skills/community/skills/`` per request through this).

    Semantics match the registry walk exactly: malformed skills land in
    ``failures`` (one human-readable string each) instead of raising;
    frontmatter-name/folder-name mismatches are failures; within-folder
    duplicate names keep the first occurrence. Records come back sorted
    by name. A missing/non-directory ``base`` yields ``([], [])`` — an
    absent community submodule is a first-class state (ADR 0027 §3),
    not an error.
    """

    records: dict[str, SkillRecord] = {}
    failures: list[str] = []
    base_path = Path(base)
    if base_path.is_dir():
        _walk_into(base_path, source=source, records=records, failures=failures, existing=set())
    return [records[name] for name in sorted(records)], failures


def load_skill_folder(folder: Path | str, *, source: SkillSource = "community") -> SkillRecord:
    """Load a single skill folder; raise :class:`LoaderError` on failure.

    Public wrapper over the per-skill parse used by the registry walk.
    Unlike :func:`scan_skills_folder` this surfaces the parse failure to
    the caller — the DE-263 install path needs the error text so a
    malformed community SKILL.md is rejected with a 422 naming the
    problem rather than silently vanishing from the catalog.

    Also enforces the frontmatter-name/folder-name match the registry
    walk enforces, so a skill that would never load into the registry
    cannot be installed either.
    """

    folder_path = Path(folder)
    record = _load_one(folder_path, source=source)
    if record.name != folder_path.name:
        raise LoaderError(
            folder_path.name,
            f"frontmatter name {record.name!r} does not match folder name {folder_path.name!r}",
        )
    return record


# --- SIGHUP wiring -----------------------------------------------------------


def install_sighup_reload(
    holder: MutableSkillRegistry,
    skills_dir: Path | str,
    community_skills_dir: Path | str | None = None,
) -> None:
    """Wire SIGHUP to atomically rebuild and swap the registry in ``holder``.

    The signal handler is installed on the main thread (Python only
    delivers signals to the main thread anyway). The handler is
    deliberately small — it builds a fresh registry via
    :func:`load_registry` and calls :meth:`MutableSkillRegistry.replace`,
    both of which are safe to invoke from a signal context (no async,
    no I/O on the event loop, no mutation of shared mutable structures
    beyond the holder's own locked swap).

    SIGHUP is unavailable on Windows; this function is a no-op there
    (with a debug log so operators on Windows know not to expect it).

    ``community_skills_dir`` is forwarded to :func:`load_registry` on
    each reload so the community submodule is re-scanned alongside the
    built-in skills when the operator sends SIGHUP.
    """

    sighup = getattr(signal, "SIGHUP", None)
    if sighup is None:
        log.debug("SIGHUP not available on this platform; reload disabled")
        return

    base = Path(skills_dir)
    cbase = Path(community_skills_dir) if community_skills_dir is not None else None

    def _handler(_signum: int, _frame: object) -> None:
        log.info(
            "SIGHUP received — reloading skill registry from %s (community: %s)",
            base,
            cbase or "none",
        )
        try:
            new_registry = load_registry(base, community_skills_dir=cbase)
        except Exception as exc:
            # A catastrophic failure (e.g., the skills directory was
            # unmounted) should not crash the process. Log and keep
            # serving the old snapshot.
            log.error(
                "skill registry reload failed; keeping prior snapshot: %s",
                exc,
                exc_info=True,
            )
            return
        old = holder.replace(new_registry)
        log.info(
            "skill registry reloaded: %d → %d skills",
            len(old.records),
            len(new_registry.records),
        )

    signal.signal(sighup, _handler)


__all__ = [
    "LoaderError",
    "install_sighup_reload",
    "load_registry",
    "load_skill_folder",
    "scan_skills_folder",
]
