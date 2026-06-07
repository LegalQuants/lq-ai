"""Prompt assembly for the autonomous executor's analysis phase — M4 real-work.

Single responsibility: take an :class:`AutonomousSession` whose ``params``
identifies a target (``skill_ref`` OR ``playbook_id``) + the retrieved chunks,
and produce a ``list[dict]`` of ``{role, content}`` messages ready for the
chokepoint's :func:`_handle_gateway_inference` (which expects ``model`` +
``messages`` in its params).

The model itself is chosen at the call site (the analysis node passes
``settings.autonomous_default_model`` or the skill/playbook's pinned model);
this module owns prompt assembly only.

Skill targets: resolved via the global ``SkillRegistry`` (mirroring
``api/app/api/internal.py:get_skill_internal``).  The skill's ``content_md``
body (the SKILL.md body markdown — see :class:`app.skills.schema.Skill`)
becomes the system prompt.  In production the registry holder lives at
``app.state.skill_registry``; tests install the same holder so this module
has one access path regardless of caller.

Playbook targets: loaded via ``select(Playbook).where(Playbook.id == ...)``
with ``selectinload(Playbook.positions)`` (mirroring
``api/app/playbooks/executor.py:205``).  The playbook's name, description,
contract type, and positions render to a deterministic markdown system
prompt.

The structured-output instruction tail :data:`STRUCTURED_OUTPUT_INSTRUCTION`
is always appended to the system prompt and tells the model exactly which
JSON keys the drafting node parses (``findings``, ``suggested_memories``,
``suggested_precedents``, ``privilege_concerns``, ``scope_concerns``).

When the session opted in to document-grade artifacts
(``session.params["emit_artifacts"]`` is truthy — Donna ask #8), the
additional :data:`ARTIFACT_OUTPUT_INSTRUCTION` tail is appended AFTER it,
documenting the optional ``artifacts`` key. Sessions that did not opt in
never see the artifact instruction, so existing automations see zero
behavior/cost change.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.autonomous import AutonomousSession
from app.models.playbook import Playbook
from app.skills.registry import MutableSkillRegistry, SkillRegistry

# ---------------------------------------------------------------------------
# Structured-output instruction tail
# ---------------------------------------------------------------------------
#
# Every analysis-phase call closes its system prompt with this block so the
# model knows exactly what JSON shape the drafting node will parse.  The
# five top-level keys (``findings``, ``suggested_memories``,
# ``suggested_precedents``, ``privilege_concerns``, ``scope_concerns``) are
# the contract; the drafting node and the structured-output parser test
# both reference them by name.  Changes here REQUIRE matching updates in
# the drafting node and a regression test.
#
# CONTRACT FOR TASK 8 (structured_output.py parser):
# The "everything else in your response is logged as a finding only if the
# JSON cannot be parsed" sentence below is a contract — the parser MUST
# implement this fallback (return a tolerant unstructured result with the
# raw content preserved, so the drafting node can emit a single fallback
# finding). If Task 8 changes this behavior, update the prompt to match
# in the same PR.

STRUCTURED_OUTPUT_INSTRUCTION = """\
After your analysis, return a final JSON object with this exact shape (and \
nothing after it):

{
  "findings": [
    {"title": "...", "summary": "...", "severity": "info|warn|critical",
     "source_chunk_ids": ["..."]}
  ],
  "suggested_memories": [
    {"category": "...", "content": "...", "rationale": "..."}
  ],
  "suggested_precedents": [
    {"pattern_kind": "...", "summary": "..."}
  ],
  "privilege_concerns": ["..."],
  "scope_concerns": ["..."]
}

All arrays may be empty.  Wrap the JSON in a ```json fenced block.  \
The JSON is parsed by the autonomous executor; everything else in your \
response is logged as a finding only if the JSON cannot be parsed.
"""


# ---------------------------------------------------------------------------
# Artifact instruction tail (opt-in — Donna ask #8)
# ---------------------------------------------------------------------------
#
# Appended AFTER ``STRUCTURED_OUTPUT_INSTRUCTION`` ONLY when the session
# opted in (``session.params["emit_artifacts"]`` is truthy).  It documents
# one ADDITIONAL optional top-level key (``artifacts``) in the same JSON
# object.  The contract spans three modules, all updated in this commit:
#
# - the parser (structured_output.py) fills ``StructuredResult.artifacts``
#   via ``_as_dict_list`` regardless of the flag (flag-agnostic by design);
# - the drafting node (nodes.py case 4) dispatches each parsed artifact
#   through the ``emit_artifact`` chokepoint ONLY when the session flag is
#   set (defense-in-depth: an un-asked-for ``artifacts`` key is ignored);
# - the chokepoint handler (guard.py::_handle_emit_artifact) takes the
#   inner ``content`` key — the drafting node maps ``content_md`` (the
#   name instructed here) onto it.
#
# Changes here REQUIRE matching updates in those three places and a
# regression test.

ARTIFACT_OUTPUT_INSTRUCTION = """\
The JSON object may also carry one ADDITIONAL optional top-level key:

  "artifacts": [
    {"name": "<filename, e.g. review-memo.md>",
     "content_md": "<the full document in markdown>"}
  ]

When the work product warrants a standalone document (a review memo, a \
summary, a report), emit it here as complete, self-contained markdown.  \
The array may be empty.  Emit at most a few artifacts — the executor \
persists each one into the run's knowledge base.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def assemble_analysis_messages(
    session: AutonomousSession,
    *,
    chunks: list[dict[str, Any]],
    db: AsyncSession,
    registry: SkillRegistry | None = None,
) -> list[dict[str, str]]:
    """Build the analysis-phase ``messages`` payload.

    Resolves the session's target (``skill_ref`` or ``playbook_id`` from
    ``session.params``) into a system prompt, formats the retrieved chunks
    as a user message, and appends :data:`STRUCTURED_OUTPUT_INSTRUCTION`
    to the system prompt.  When the session opted in to artifacts
    (``session.params["emit_artifacts"]`` is truthy),
    :data:`ARTIFACT_OUTPUT_INSTRUCTION` is appended after it; otherwise
    the model is never told about the ``artifacts`` key.

    Args:
        session: The autonomous session.  ``session.params`` must carry
            exactly one of ``skill_ref`` (str) or ``playbook_id`` (UUID
            string).  If both are present, ``skill_ref`` wins (mirrors
            the precedence in the executor's intake handling).
        chunks: The retrieved-chunks list shaped like
            :func:`app.autonomous.guard._handle_retrieve_chunks`'s
            output — each dict carries ``chunk_id``, ``document_id``,
            ``file_id``, ``content``, ``file_name``,
            ``char_offset_start`` / ``char_offset_end``.  May be empty.
        db: Active async ORM session.  Used only when the target is a
            playbook (skill lookup goes through the in-memory registry).
        registry: Optional skill registry snapshot.  When ``None``, the
            module reads ``app.state.skill_registry`` (the production
            access path).  Tests can pass a known snapshot to avoid
            depending on FastAPI lifespan.

    Returns:
        A two-element ``[system, user]`` list of ``{role, content}``
        dicts.  The system message carries the SKILL.md body OR the
        playbook render plus :data:`STRUCTURED_OUTPUT_INSTRUCTION`; the
        user message carries the retrieved chunks.

    Raises:
        ValueError: If neither ``skill_ref`` nor ``playbook_id`` is set
            in ``session.params``, or if the named skill is not in the
            registry, or if the playbook id does not resolve to a row.
    """
    params = session.params or {}
    skill_ref = params.get("skill_ref")
    playbook_id_raw = params.get("playbook_id")

    if skill_ref:
        system = await _load_skill_system_prompt(str(skill_ref), registry=registry)
    elif playbook_id_raw:
        system = await _load_playbook_system_prompt(
            uuid.UUID(str(playbook_id_raw)),
            db=db,
        )
    else:
        raise ValueError(
            "assemble_analysis_messages: session has no skill_ref or playbook_id in params"
        )

    user_chunks = _format_chunks_as_user_content(chunks)
    full_system = system + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION
    # Opt-in only (Donna ask #8): the artifact instruction is appended iff
    # the spawn path copied ``emit_artifacts`` into the session params —
    # non-opted-in sessions never pay the extra output tokens.
    if (session.params or {}).get("emit_artifacts"):
        full_system = full_system + "\n" + ARTIFACT_OUTPUT_INSTRUCTION
    return [
        {"role": "system", "content": full_system},
        {"role": "user", "content": user_chunks},
    ]


# ---------------------------------------------------------------------------
# Skill resolution
# ---------------------------------------------------------------------------


async def _load_skill_system_prompt(
    skill_ref: str,
    *,
    registry: SkillRegistry | None,
) -> str:
    """Return the ``content_md`` body for ``skill_ref`` as a system prompt.

    Mirrors :func:`app.api.internal.get_skill_internal`'s registry
    lookup (no user/team shadow resolution — the autonomous layer
    operates on the filesystem-canonical registry view at A2/B3 maturity).

    Raises ``ValueError`` if the skill is not in the registry.
    """
    snapshot = registry if registry is not None else _registry_from_app_state()
    if snapshot is None:
        raise ValueError(
            f"assemble_analysis_messages: skill registry not initialised (skill_ref={skill_ref!r})"
        )
    skill = snapshot.get_skill(skill_ref)
    if skill is None:
        raise ValueError(f"assemble_analysis_messages: skill {skill_ref!r} not in the registry")
    return skill.content_md


def _registry_from_app_state() -> SkillRegistry | None:
    """Return the current ``SkillRegistry`` snapshot from ``app.state``, or None.

    Both production startup paths install a :class:`MutableSkillRegistry`
    at ``app.state.skill_registry`` via
    :func:`app.skills.bootstrap.install_skill_registry` — the FastAPI
    lifespan (``app/main.py``) and the arq worker's startup hook
    (``app/workers/arq_setup.on_startup``), because this module runs in
    whichever process executes the session.  Tests that want this
    default path install the same holder.  Callers that pass an
    explicit ``registry=`` bypass this helper entirely.

    The import of :mod:`app.main` is deferred to function-call time to
    avoid circular imports — ``main.py`` already imports from
    :mod:`app.autonomous` at module load.
    """
    # Deferred import: app.main imports from app.autonomous at startup.
    from app.main import app

    holder: MutableSkillRegistry | None = getattr(app.state, "skill_registry", None)
    if holder is None:
        return None
    return holder.current()


# ---------------------------------------------------------------------------
# Playbook resolution
# ---------------------------------------------------------------------------


async def _load_playbook_system_prompt(playbook_id: uuid.UUID, *, db: AsyncSession) -> str:
    """Render the playbook + positions to a deterministic system prompt.

    Mirrors the eager-load pattern in
    ``app/playbooks/executor.py:205`` so the per-position walk picks
    up rows in ``position_order`` ASC.

    Raises ``ValueError`` if no playbook row matches ``playbook_id``.
    """
    stmt = (
        select(Playbook)
        .where(Playbook.id == playbook_id, Playbook.deleted_at.is_(None))
        .options(selectinload(Playbook.positions))
    )
    playbook = (await db.execute(stmt)).scalar_one_or_none()
    if playbook is None:
        raise ValueError(f"assemble_analysis_messages: playbook {playbook_id!s} not found")

    lines: list[str] = [
        f"# Playbook: {playbook.name}",
        "",
        f"Contract type: {playbook.contract_type}",
        f"Version: {playbook.version}",
    ]
    if playbook.description:
        lines += ["", playbook.description]

    if playbook.positions:
        lines += ["", "## Positions"]
        for pos in playbook.positions:
            lines.append("")
            lines.append(f"### {pos.position_order + 1}. {pos.issue}")
            lines.append(f"Severity if missing: {pos.severity_if_missing}")
            if pos.description:
                lines += ["", pos.description]
            lines += [
                "",
                "Standard language:",
                "",
                pos.standard_language,
            ]
            if pos.redline_strategy:
                lines += [
                    "",
                    f"Redline strategy: {pos.redline_strategy}",
                ]
            if pos.fallback_tiers:
                lines += ["", "Fallback tiers:"]
                for tier in pos.fallback_tiers:
                    rank = tier.get("rank")
                    desc = tier.get("description") or ""
                    lang = tier.get("language") or ""
                    lines.append(f"- rank {rank}: {desc}")
                    if lang:
                        lines.extend(["", "  Language:", "", f"  {lang}"])
    else:
        lines += ["", "(No positions defined.)"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chunk formatting
# ---------------------------------------------------------------------------


def _format_chunks_as_user_content(chunks: list[dict[str, Any]]) -> str:
    """Render the retrieved chunks as a single user-role message.

    Layout per chunk::

        [chunk_id <uuid> | file_id <uuid> | file <name> | offsets <start>-<end>]
        <content>

    Chunks are joined by blank lines.  The marker ``[chunk_id`` is what
    the model uses to cite a chunk back into a finding's
    ``source_chunk_ids`` (and what the test asserts on).

    If ``chunks`` is empty, returns a placeholder so the user message is
    never zero-length (which some providers reject).
    """
    if not chunks:
        return "CHUNKS: (no chunks retrieved for this run)"

    blocks: list[str] = ["CHUNKS:"]
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id", "?")
        file_id = chunk.get("file_id", "?")
        file_name = chunk.get("file_name", "?")
        start = chunk.get("char_offset_start", "?")
        end = chunk.get("char_offset_end", "?")
        content = chunk.get("content", "")
        header = (
            f"[chunk_id {chunk_id} | file_id {file_id} | file {file_name} | offsets {start}-{end}]"
        )
        blocks.append(f"{header}\n{content}")
    return "\n\n".join(blocks)


__all__ = [
    "ARTIFACT_OUTPUT_INSTRUCTION",
    "STRUCTURED_OUTPUT_INSTRUCTION",
    "assemble_analysis_messages",
]
