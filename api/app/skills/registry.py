"""In-memory skill registry with atomic-swap reload.

The registry maps ``name`` → :class:`SkillRecord` (a small struct
binding the parsed frontmatter, the body markdown, the raw YAML, and
the absolute path on disk). Reads — by both the API handlers and any
future C2 consumers — go through :meth:`SkillRegistry.list_summaries`
and :meth:`SkillRegistry.get_skill`.

Reload semantics: the loader builds a fresh :class:`SkillRegistry`
instance from the filesystem, and the live registry is *swapped*
atomically inside :class:`MutableSkillRegistry` (a thin holder used by
the lifespan handler). In-flight requests holding a reference to the
old registry continue to see the old state for the duration of their
handler call; new requests pick up the new state immediately. The swap
is a single Python attribute assignment, which is thread-safe under the
GIL — there's no torn read scenario.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.skills.schema import (
    Skill,
    SkillFile,
    SkillFrontmatter,
    SkillSource,
    SkillSummary,
    derive_summary,
)


@dataclass(frozen=True)
class SkillRecord:
    """One skill in the registry.

    The frontmatter and body are parsed/validated up front; reference
    and example file *contents* are loaded lazily by the public API
    when the full skill is requested.
    """

    name: str
    folder: Path
    frontmatter: SkillFrontmatter
    raw_yaml: str
    """The verbatim YAML frontmatter block (between the leading ``---``
    delimiters), preserved so the API can echo it back to clients
    that want to round-trip skill content."""
    body: str
    """The body markdown — everything after the closing ``---``."""
    source: SkillSource = "built-in"
    """Origin of this skill: ``"built-in"`` for skills from ``skills/``;
    ``"community"`` for skills from the lq-skills submodule at
    ``skills/community/skills/``. Set by the loader; not parsed from
    the frontmatter — the loader derives it from which directory the
    skill was found in."""
    reference_paths: tuple[Path, ...] = field(default_factory=tuple)
    example_paths: tuple[Path, ...] = field(default_factory=tuple)
    script_paths: tuple[Path, ...] = field(default_factory=tuple)

    def summary(self) -> SkillSummary:
        return derive_summary(self.name, self.frontmatter, source=self.source)

    def materialise(self) -> Skill:
        """Build the full :class:`Skill` shape, loading reference and
        example file contents from disk lazily."""

        summary = self.summary()  # already carries source via derive_summary
        reference_files = tuple(_read_files(self.folder, self.reference_paths))
        example_files = tuple(_read_files(self.folder, self.example_paths))
        return Skill(
            **summary.model_dump(),
            content_yaml=self.raw_yaml,
            content_md=self.body,
            reference_files=list(reference_files),
            example_files=list(example_files),
            script_files=list(_read_files(self.folder, self.script_paths)),
        )


def _read_files(folder: Path, paths: tuple[Path, ...]) -> list[SkillFile]:
    out: list[SkillFile] = []
    for abs_path in paths:
        try:
            content = abs_path.read_text(encoding="utf-8")
        except OSError:
            # File disappeared between scan and read (rare; an operator
            # editing the skills directory at runtime). Skip rather than
            # surface a 500 — the rest of the skill is still useful.
            continue
        rel = abs_path.relative_to(folder)
        out.append(SkillFile(path=str(rel), content=content))
    return out


@dataclass(frozen=True)
class SkillRegistry:
    """Immutable snapshot of all loaded skills.

    Use the helpers (:meth:`names`, :meth:`get`, :meth:`list_summaries`,
    :meth:`get_skill`) rather than reading ``records`` directly.
    """

    records: dict[str, SkillRecord]

    def names(self) -> list[str]:
        return sorted(self.records.keys())

    def get(self, name: str) -> SkillRecord | None:
        return self.records.get(name)

    def list_summaries(self, *, tag: str | None = None) -> list[SkillSummary]:
        """Return every skill's :class:`SkillSummary`, sorted by name.

        ``tag`` filters to skills whose frontmatter ``tags`` includes
        the given value (case-insensitive). Matches the
        ``GET /api/v1/skills?tag=...`` query parameter in the OpenAPI
        sketch.
        """

        summaries: list[SkillSummary] = []
        tag_lower = tag.lower() if tag else None
        for name in self.names():
            rec = self.records[name]
            summary = rec.summary()
            if tag_lower is not None and not any(t.lower() == tag_lower for t in summary.tags):
                continue
            summaries.append(summary)
        return summaries

    def get_skill(self, name: str) -> Skill | None:
        rec = self.get(name)
        if rec is None:
            return None
        return rec.materialise()


class MutableSkillRegistry:
    """Thin holder that supports atomic swap of the underlying registry.

    The lifespan handler builds the initial :class:`SkillRegistry` and
    wraps it in a :class:`MutableSkillRegistry`. The SIGHUP handler
    rebuilds and calls :meth:`replace` to swap in the new snapshot.

    Reads go through :meth:`current`, which is a single attribute
    fetch — atomic under CPython's GIL. No torn reads, no partial
    state visible to callers.
    """

    def __init__(self, initial: SkillRegistry) -> None:
        self._registry = initial
        # `_lock` protects the *write side*: it serialises concurrent
        # reload attempts. Reads do not take the lock; they read the
        # `_registry` reference once and operate on the snapshot.
        self._lock = threading.Lock()

    def current(self) -> SkillRegistry:
        return self._registry

    def replace(self, new_registry: SkillRegistry) -> SkillRegistry:
        """Swap in ``new_registry`` and return the prior snapshot."""

        with self._lock:
            old = self._registry
            self._registry = new_registry
            return old


__all__ = ["MutableSkillRegistry", "SkillRecord", "SkillRegistry"]
