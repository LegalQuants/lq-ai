"""Pydantic schemas for skill frontmatter and the wire shapes.

Two layers:

* :class:`SkillFrontmatter` / :class:`LQAIFrontmatter` — what we parse
  out of each ``SKILL.md``'s YAML front-matter block. Matches the
  conventions in ``docs/skill-authoring-guide.md`` but is **permissive**:
  unknown fields are kept (``model_config.extra = "allow"``), and most
  fields are optional because the M1 starter skills predate the formal
  guide and use a wider range of values (e.g., ``output_format:
  markdown`` rather than ``report``; some skills carry no ``lq_ai:``
  block at all). The loader emits a WARNING per skill when a strictly-
  required field is missing; it does not fail the whole startup.

* :class:`SkillSummary` / :class:`Skill` — the JSON shapes the backend
  API returns. Match the ``SkillSummary`` and ``Skill`` schemas in
  ``docs/api/backend-openapi.yaml``. ``SkillSummary`` is what
  ``GET /api/v1/skills`` returns per item; ``Skill`` is what
  ``GET /api/v1/skills/{skill_name}`` returns and includes the full
  body, the raw YAML frontmatter, the optional reference files, and
  the optional example files.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# All built-in M1 skills are filesystem-canonical; user/team-scope forks
# land later and gain ``user`` / ``team`` values for ``scope``. C1 only
# delivers the ``builtin`` scope.
SkillScope = Literal["builtin", "user", "team"]

# ``source`` distinguishes skills loaded from the repo's own ``skills/``
# directory ("built-in") from skills loaded from the community submodule
# at ``skills/community/skills/`` ("community"). User/team-scope skills
# (DB-backed forks) carry ``source: "user"`` or ``source: "team"`` which
# mirrors their ``scope`` value — the frontend can use ``source`` for
# badge rendering without inspecting ``scope``.
SkillSource = Literal["built-in", "community", "user", "team"]


class ColumnSpec(BaseModel):
    """One column in an ``output_format: table`` Skill (M3-C1).

    A table-mode skill produces a row-per-document by column-per-spec
    grid; each column carries its own per-row extraction query plus
    optional overrides for the skill-level ``ensemble_verification``
    and ``minimum_inference_tier``. The Tabular Review LangGraph
    workflow (M3-C2) dispatches one Citation-Engine-grounded extraction
    per ``(document, column)`` cell.

    Per Decision C-1 (Phase C prep, 2026-05-21): every cell value is a
    string in v0.3.0; typed columns are a follow-on DE if user-attorney
    walkthrough surfaces the need.
    """

    name: str
    """The grid column header. Required."""

    query: str
    """The per-row extraction prompt instantiated against each document.
    Required."""

    ensemble_verification: bool | None = None
    """When ``True``, this column's cells route through Stage 4 of the
    Citation Engine cascade (ensemble verification). Overrides the
    skill-level field when both are set. ``None`` means 'inherit from
    skill / project / deployment default'."""

    minimum_inference_tier: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Per-column tier floor (1-5). Overrides the skill-level "
        "tier floor when both are set. High-stakes columns can demand Tier 4+ "
        "while routine columns route Tier 1.",
    )


class LQAIFrontmatter(BaseModel):
    """The ``lq_ai:`` namespace inside a SKILL.md's frontmatter.

    All fields are optional. The skill-authoring guide documents
    recommended values, but the M1 starter skill corpus uses a broader
    range — strict validation would reject most of it. The summary
    endpoint surfaces what is present; missing fields are simply not
    in the response.
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    """Human-readable display name for the UI. Defaults to ``name``
    rendered title-cased when missing."""

    version: str | None = Field(
        default=None,
        description="Semver string, e.g. '1.0.0'. Free-form so we can surface "
        "non-conforming values without rejecting them.",
    )

    author: str | None = None

    tags: list[str] = Field(default_factory=list)
    """Discovery tags. Empty if not declared."""

    jurisdiction: str | None = None
    """Free-form per the corpus reality (``us``, ``regime-aware``,
    ``agnostic``, ``regime-dependent``, ``US-default``, etc.)."""

    output_format: str | None = None
    """Free-form per corpus (``report``, ``markdown``,
    ``structured_checklist``, ``redline``, ``table``, etc.).

    The ``table`` value (M3-C1) signals to the Tabular Review surface that
    this skill produces a grid; the column spec lives in :attr:`columns`."""

    columns: list[ColumnSpec] | None = None
    """Column definitions for an ``output_format: table`` skill (M3-C1).

    ``None`` for non-table skills. The loader (``app/skills/loader.py``)
    emits a WARNING and skips the skill when ``output_format == 'table'``
    but ``columns`` is missing or empty — mirroring the existing pattern
    for required-but-missing fields. A non-table skill may carry a
    ``columns`` value (e.g., a skill author iterating on output mode);
    downstream surfaces ignore it unless ``output_format == 'table'``."""

    minimum_inference_tier: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Tier-floor declaration; the gateway's tier-floor "
        "enforcement (D1) consults this. C1 only surfaces the value.",
    )

    ensemble_verification: bool | None = Field(
        default=None,
        description="When true, the Citation Engine runs Stage 4 (ensemble "
        "verification) for citations produced from chats using this skill. "
        "Per M2-D1, OR'd against the chat's project ensemble flag and the "
        "gateway's deployment default. None means 'no opinion' (treated as "
        "false at the OR site).",
    )

    use_organization_profile: bool | None = None
    is_organization_profile: bool | None = None
    self_improvement: bool | None = None

    trigger_examples: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _table_mode_requires_columns(self) -> LQAIFrontmatter:
        """``output_format: table`` requires a non-empty ``columns`` list.

        Enforced at model layer so the loader's existing
        ``ValidationError → LoaderError → WARNING → skip`` path catches
        malformed table-mode skills the same way it catches any other
        frontmatter mistake (per Decision C-1, M3-C1).
        """

        if self.output_format == "table" and not self.columns:
            raise ValueError(
                "output_format: table requires a non-empty 'columns' list "
                "(see docs/skill-authoring-guide.md §Table-mode skills)"
            )
        return self


class SkillFrontmatter(BaseModel):
    """Top-level frontmatter shape.

    Two required fields — ``name`` and ``description``. ``name`` is the
    skill's stable identifier (matches the folder name); ``description``
    is the one-sentence trigger statement. Everything else nests under
    ``lq_ai:`` per the authoring guide.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    lq_ai: LQAIFrontmatter = Field(default_factory=LQAIFrontmatter)


# --- Wire shapes -------------------------------------------------------------


class SkillSummary(BaseModel):
    """The shape ``GET /api/v1/skills`` returns per item.

    Mirrors ``SkillSummary`` in ``docs/api/backend-openapi.yaml``. The
    ``required`` set there is ``[name, version, scope, title]``; for
    skills whose frontmatter is sparse we default ``version`` to
    ``"unversioned"`` and ``title`` to a humanised form of ``name`` so
    the contract is honoured even when the source is incomplete.
    """

    name: str
    version: str
    scope: SkillScope
    title: str
    source: SkillSource = "built-in"
    """Attribution field: ``"built-in"`` for skills from ``skills/``,
    ``"community"`` for skills loaded via the lq-skills submodule at
    ``skills/community/skills/``. User/team-scope DB-backed skills carry
    ``"user"`` or ``"team"`` respectively."""
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    minimum_inference_tier: int | None = None
    ensemble_verification: bool | None = None
    output_format: str | None = None


class SkillFile(BaseModel):
    """A reference or example file relative to the skill folder."""

    path: str
    """Path relative to the skill folder, e.g. ``reference/severity_rubric.md``."""

    content: str


class Skill(SkillSummary):
    """The shape ``GET /api/v1/skills/{name}`` returns.

    Mirrors ``Skill`` in ``docs/api/backend-openapi.yaml`` (which is an
    ``allOf`` of ``SkillSummary`` plus body fields). ``content_yaml`` is
    the raw frontmatter block (re-emitted, not the source bytes), and
    ``content_md`` is the body markdown. Reference and example files
    are loaded lazily — only when this shape is materialised.

    Wave D.2 — ``id`` surfaces the underlying ``user_skills.id`` row UUID
    when the resolved scope is ``user`` or ``team``. Built-in
    (filesystem-canonical) skills have no DB row and return ``None``.
    The skill detail page's Versions tab needs this id to call the
    audit-history endpoint; surfacing it on the detail GET avoids a
    second round-trip to look it up by slug.
    """

    id: str | None = None
    content_yaml: str
    content_md: str
    reference_files: list[SkillFile] = Field(default_factory=list)
    example_files: list[SkillFile] = Field(default_factory=list)


# --- Skill inputs (PRD §3.4 skill-input-form pattern) -----------------------
#
# Skills declare required + optional inputs in their frontmatter so the
# application can render a form before invoking the skill. The corpus
# reality is inconsistent — some skills nest ``inputs`` under ``lq_ai:``
# (e.g., enhance-prompt) while the formal guide puts it at the top
# level. The helper in this module looks in both places.


class SkillInputDef(BaseModel):
    """One declared input — the shape the skill-input form renders against.

    Fields per ``docs/skill-authoring-guide.md`` + observed corpus
    variance. ``name`` is the only strictly required field; the form can
    render a text input as the default when ``type`` is absent.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    type: str | None = None
    """One of ``text`` | ``enum`` | ``boolean`` | ``integer`` |
    ``structured`` | ``file`` — free-form per corpus reality; the form
    renderer chooses a sensible default when null."""

    required: bool = False
    description: str | None = None
    enum: list[str] | None = None
    default: Any | None = None


class SkillInputs(BaseModel):
    """The shape ``GET /api/v1/skills/{name}/inputs`` returns."""

    name: str
    required: list[SkillInputDef] = Field(default_factory=list)
    optional: list[SkillInputDef] = Field(default_factory=list)


def _coerce_input_entry(entry: Any, *, required: bool) -> SkillInputDef | None:
    """Turn one frontmatter inputs entry into a SkillInputDef.

    Two corpus shapes appear in the wild:

    * Bare string (the formal guide's example): ``- document``. We treat
      these as ``{name: "document", type: null}``.
    * Dict (the corpus reality for enhance-prompt): ``{name, type,
      description}``. We pass through the dict fields.

    Anything else (non-string, non-dict; or dict missing ``name``)
    returns ``None`` so the resolver can skip silently rather than
    fail the whole inputs endpoint on a malformed entry.
    """

    if isinstance(entry, str):
        return SkillInputDef(name=entry, required=required)
    if isinstance(entry, dict):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            return None
        data = {**entry, "required": required}
        try:
            return SkillInputDef.model_validate(data)
        except Exception:
            # Malformed entry — surface as a name-only stub rather than
            # 500 the whole inspector endpoint.
            return SkillInputDef(name=name, required=required)
    return None


def extract_inputs(name: str, frontmatter: SkillFrontmatter) -> SkillInputs:
    """Return the skill-input form schema for ``name``.

    Looks for ``inputs:`` at the top level of the frontmatter first
    (formal guide shape), then under ``lq_ai.inputs`` (corpus reality
    for enhance-prompt). When neither is present, returns an empty
    schema — meaning "no declared inputs; the skill is purely prompted."
    """

    extras = frontmatter.model_extra or {}
    inputs_block: Any | None = extras.get("inputs")

    if not isinstance(inputs_block, dict):
        lq_extras = frontmatter.lq_ai.model_extra or {}
        inputs_block = lq_extras.get("inputs")

    if not isinstance(inputs_block, dict):
        return SkillInputs(name=name)

    required_entries = inputs_block.get("required") or []
    optional_entries = inputs_block.get("optional") or []

    required: list[SkillInputDef] = []
    if isinstance(required_entries, list):
        for entry in required_entries:
            coerced = _coerce_input_entry(entry, required=True)
            if coerced is not None:
                required.append(coerced)

    optional: list[SkillInputDef] = []
    if isinstance(optional_entries, list):
        for entry in optional_entries:
            coerced = _coerce_input_entry(entry, required=False)
            if coerced is not None:
                optional.append(coerced)

    return SkillInputs(name=name, required=required, optional=optional)


# --- Internal helpers --------------------------------------------------------


def derive_summary(
    name: str,
    frontmatter: SkillFrontmatter,
    *,
    source: SkillSource = "built-in",
) -> SkillSummary:
    """Build a :class:`SkillSummary` from parsed frontmatter.

    Applies the contract-completion defaults documented above so the
    OpenAPI ``required`` set is always satisfied even when the source
    frontmatter is sparse.

    ``source`` distinguishes the origin of the skill:
    * ``"built-in"`` — loaded from the repo's own ``skills/`` directory.
    * ``"community"`` — loaded from ``skills/community/skills/`` (the
      lq-skills submodule).
    Callers that do not pass ``source`` get ``"built-in"`` to preserve
    backward compatibility.
    """

    lq = frontmatter.lq_ai
    title = lq.title or _humanise(name)
    version = lq.version or "unversioned"
    return SkillSummary(
        name=name,
        version=version,
        scope="builtin",
        source=source,
        title=title,
        description=frontmatter.description,
        tags=list(lq.tags),
        jurisdiction=lq.jurisdiction,
        minimum_inference_tier=lq.minimum_inference_tier,
        ensemble_verification=lq.ensemble_verification,
        output_format=lq.output_format,
    )


def _humanise(name: str) -> str:
    """Turn ``msa-review-saas`` into ``Msa Review Saas``.

    Used as a fallback display name when the frontmatter omits ``title``.
    Not pretty for every name, but visible when present and explicit
    when absent — fixing it is a one-line frontmatter edit per skill.
    """

    return " ".join(part.capitalize() for part in name.split("-")) if name else name


def filter_summary_for_response(summary: SkillSummary) -> dict[str, Any]:
    """Return the summary as a dict with ``None``-valued optionals dropped.

    The OpenAPI sketch lists ``description``, ``tags``, ``jurisdiction``,
    ``minimum_inference_tier``, and ``output_format`` as optional. We
    omit them rather than emit ``null`` so the response stays compact
    and matches the sketch's "optional == may be absent" reading.

    ``source`` is always present (it has a non-null default) so it is
    never filtered out — the frontend can always read it for badge
    rendering without a defensive check.
    """

    raw = summary.model_dump()
    return {k: v for k, v in raw.items() if v is not None and v != []}


__all__ = [
    "ColumnSpec",
    "LQAIFrontmatter",
    "Skill",
    "SkillFile",
    "SkillFrontmatter",
    "SkillInputDef",
    "SkillInputs",
    "SkillScope",
    "SkillSource",
    "SkillSummary",
    "derive_summary",
    "extract_inputs",
    "filter_summary_for_response",
]
