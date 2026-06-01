"""Skill prompt assembler — body, references, inputs (C2).

Pure-Python; no I/O. Inputs are the already-fetched :class:`Skill`
objects (from :class:`app.clients.backend.BackendClient`) plus the
caller-supplied input bindings; output is the assembled system-message
text. The HTTP boundary lives in :mod:`app.clients.backend`; the chat-
completion boundary lives in :mod:`app.api.inference`. Keeping the
assembler in the middle makes it easy to unit-test all three of
substitution / reference-injection / system-message merging without
touching the wire.

Templating
----------

Per ADR 0006, skill-input substitution is a regex-based ``{{name}}``
matcher. Variables are bounded to ``[a-zA-Z_][a-zA-Z0-9_]*``; values
are inserted verbatim (no escaping, no expression evaluation). Unknown
variables are left in place — the model sees the literal ``{{x}}`` and
can ignore it; surplus inputs the body never references are tolerated.

System-message handling
-----------------------

The assembled skill content is *prepended* to any existing system
message in the request. If no system message exists, a new one is
created. Skill content first, then a clear separator, then the user's
original system message. Multiple skills concatenate in caller-supplied
order, each separated by a divider so the model can see the boundary.

Reference files
---------------

Each skill's ``reference_files`` (markdown text in the skill's
``reference/`` folder) is appended to that skill's section under a
clear ``## Reference: <path>`` header. Reference content is verbatim;
the model sees both the skill's instructions and the reference exhibits
in one block.

Required-input enforcement
--------------------------

Skills declare inputs via the loose ``inputs.required`` /
``inputs.optional`` blocks in their frontmatter (the M1 corpus
convention). The assembler reads ``content_yaml`` to find the
required-input list (the loader's permissive schema doesn't expose
inputs as a typed field on the parsed Skill yet). A missing required
input raises :class:`app.errors.SkillInputMissing` with the missing
field names in ``details.missing``. Optional inputs that aren't
supplied are simply not substituted.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

import yaml

from app.clients.backend import Skill
from app.errors import SkillInputMissing

log = logging.getLogger(__name__)

# Regex for ``{{var}}`` substitution. Per ADR 0006, variable names are
# bounded to a conservative identifier shape so a stray ``{{}}`` or
# ``{{ x.y }}`` cannot accidentally fire substitution.
SKILL_INPUT_VARIABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}"
)

# Section separator between concatenated skills. The textual marker is
# verbose on purpose — the model should clearly see "skill A ends here,
# skill B begins here" without ambiguity.
_SKILL_SEPARATOR: Final[str] = "\n\n---\n\n"

# Header used when prepending skill content to an existing system
# message. The model sees: skill block, separator, original system
# instruction.
_PREPEND_SEPARATOR: Final[str] = "\n\n---\n\n## Operator system instructions\n\n"


def interpolate(
    template: str,
    bindings: dict[str, Any],
    *,
    consumed: set[str] | None = None,
) -> str:
    """Substitute ``{{name}}`` placeholders with values from ``bindings``.

    Unknown variables are left in place. Non-string values are
    rendered with :func:`str`. Permissive in both directions:

    * ``interpolate("hello {{name}}", {"name": "Ada"}) == "hello Ada"``
    * ``interpolate("hello {{name}}", {})              == "hello {{name}}"``
    * ``interpolate("hi", {"unused": "x"})             == "hi"``

    Optional out-param ``consumed``: if a mutable set is passed, every
    binding key that was actually substituted by a ``{{placeholder}}``
    is added to it. This lets callers (DE-328) detect which bound
    inputs the template never referenced so they can surface them
    elsewhere instead of silently dropping them. The return value and
    substitution behavior are unchanged whether or not ``consumed`` is
    passed — existing callers that omit it are unaffected.
    """

    def _replace(match: re.Match[str]) -> str:
        var = match.group(1)
        if var in bindings:
            if consumed is not None:
                consumed.add(var)
            value = bindings[var]
            if value is None:
                return ""
            return str(value)
        # Leave the placeholder intact for the model to handle.
        return match.group(0)

    return SKILL_INPUT_VARIABLE_RE.sub(_replace, template)


def consumes_organization_profile(skill: Skill) -> bool:
    """Return True iff the skill wants the Organization Profile prepended.

    The PRD §3.12 default is opt-in: the Profile shapes every skill
    unless the skill's frontmatter sets ``lq_ai.use_organization_profile:
    false``. We re-parse the verbatim ``content_yaml`` here for the
    same reason :func:`extract_required_inputs` does — the loader's
    permissive schema doesn't expose the field as a typed attribute on
    :class:`Skill`.

    A YAML parse failure or unexpected structure is treated as opt-in
    (the default); the conservative choice is "user gets Profile-shaped
    output unless they explicitly opted out", because operating
    deployments will set Profiles expecting them to apply broadly.

    The Profile itself opts out (its synthesized frontmatter sets
    ``use_organization_profile: false``) so the assembler never tries
    to recursively prepend the Profile to itself.
    """

    try:
        parsed = yaml.safe_load(skill.content_yaml or "") or {}
    except yaml.YAMLError:
        return True

    if not isinstance(parsed, dict):
        return True

    # The flag may live at the top level (gateway's synthesized profile
    # YAML, where there's no nested ``lq_ai:`` block) or under the
    # ``lq_ai:`` block (real filesystem skills, per the authoring guide).
    # Check both spellings; the explicit-false in either wins.
    candidates: list[Any] = [parsed.get("use_organization_profile")]
    nested = parsed.get("lq_ai")
    if isinstance(nested, dict):
        candidates.append(nested.get("use_organization_profile"))

    return all(value is not False for value in candidates)


def extract_required_inputs(skill: Skill) -> list[str]:
    """Return the list of required-input names declared in the skill's frontmatter.

    The M1 corpus convention places inputs under a top-level
    ``inputs:`` block:

        inputs:
          required:
            - name: document
              type: document
              ...
          optional:
            - name: jurisdiction
              ...

    The loader's :class:`SkillFrontmatter` schema is permissive (it
    keeps unknown fields via ``extra="allow"``) but does not expose
    inputs as a typed field. We re-parse the verbatim YAML
    (``content_yaml``) here to surface the list. If the YAML can't be
    parsed or the structure isn't what we expect, we return an empty
    list — the corpus has skills with no inputs at all, and a skill
    that simply doesn't declare required inputs is fine.
    """

    try:
        parsed = yaml.safe_load(skill.content_yaml or "") or {}
    except yaml.YAMLError:
        log.warning(
            "could not re-parse skill frontmatter for inputs: name=%s",
            skill.name,
        )
        return []

    if not isinstance(parsed, dict):
        return []

    inputs = parsed.get("inputs")
    if not isinstance(inputs, dict):
        return []

    required = inputs.get("required") or []
    if not isinstance(required, list):
        return []

    names: list[str] = []
    for item in required:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
        elif isinstance(item, str):
            # Some skills may declare ``required: [foo, bar]``.
            names.append(item)
    return names


@dataclass(frozen=True)
class _AssembledSkill:
    """Internal: the concatenable text block produced for one skill."""

    name: str
    text: str


def _render_skill(skill: Skill, *, inputs: dict[str, Any]) -> _AssembledSkill:
    """Render one skill's body + references with input substitution applied."""

    parts: list[str] = []
    header = f"# Skill: {skill.title or skill.name}"
    if skill.version and skill.version != "unversioned":
        header = f"{header} (v{skill.version})"
    parts.append(header)

    if skill.description:
        parts.append(skill.description)

    # Track which bound input keys are actually consumed by a
    # ``{{placeholder}}`` across the body and every reference file, so
    # we can surface the leftovers (DE-328) rather than dropping them.
    consumed: set[str] = set()

    # Body markdown — apply substitution to the body text.
    body = interpolate(skill.content_md or "", inputs, consumed=consumed)
    parts.append(body.strip("\n"))

    # Reference files — appended verbatim with clear delimiters so the
    # model can tell skill body from reference exhibit. We also apply
    # substitution to reference content because some skills include
    # placeholder-bearing reference files (e.g., a rubric template
    # that says "for {{counterparty}} ..."); permissive substitution
    # is the right default.
    for ref in skill.reference_files:
        ref_body = interpolate(ref.content or "", inputs, consumed=consumed)
        parts.append(f"## Reference: {ref.path}\n\n{ref_body.strip()}\n")

    # DE-328 (Option A) — surface caller-bound inputs that no
    # ``{{placeholder}}`` consumed. None of the built-in skill bodies use
    # ``{{}}`` tokens, so without this the collected inputs (jurisdiction,
    # audience, text, …) would vanish before reaching the model. We append
    # a single labelled block per skill listing each leftover input whose
    # value is non-empty. Insertion order of ``inputs`` is preserved.
    # Templated skills whose inputs are all consumed get no block (no
    # duplication); a skill with no leftover inputs gets no block.
    leftover = [k for k in inputs if k not in consumed]
    leftover_lines: list[str] = []
    for key in leftover:
        value = inputs[key]
        if value is None or value == "":
            continue
        leftover_lines.append(f"- {key}: {value!s}")
    if leftover_lines:
        display = skill.title or skill.name
        block = f"### Provided inputs for {display}\n\n" + "\n".join(leftover_lines)
        parts.append(block)

    return _AssembledSkill(name=skill.name, text="\n\n".join(parts).strip())


def assemble_skill_prompt(
    skills: list[Skill],
    *,
    skill_inputs: dict[str, dict[str, Any]] | None = None,
    existing_system_message: str | None = None,
    organization_profile: Skill | None = None,
) -> str:
    """Build the system-prompt block from the given skills.

    Args:
        skills: Already-fetched skill objects, in the order the caller
            wants them concatenated.
        skill_inputs: Per-skill input bindings, keyed by skill name. The
            inner dict maps input variable names to values.
        existing_system_message: The user's pre-existing system message
            (if any). When non-empty, the assembled skill block is
            *prepended* to it with a clear separator.
        organization_profile: D4 — the deployment's Organization
            Profile, if one is set. When provided AND at least one
            attached skill consumes it (per
            :func:`consumes_organization_profile`), the Profile is
            rendered as the first section of the assembled prompt so
            org-wide voice / templates frame every downstream skill
            section. The Profile is omitted when all attached skills
            opt out, when no skills are attached, or when ``None`` is
            passed (no Profile set on the deployment).

    Returns:
        A single string ready to drop into the gateway's system message.

    Raises:
        SkillInputMissing: A skill's frontmatter declared one or more
            required inputs that the caller did not bind.
    """

    if not skills:
        return existing_system_message or ""

    skill_inputs = skill_inputs or {}

    # 1) Required-input enforcement. We collect the *full* set of
    # missing fields across all attached skills before raising so the
    # client sees one error listing every missing field rather than
    # receiving them one at a time.
    missing_by_skill: dict[str, list[str]] = {}
    for skill in skills:
        bindings = skill_inputs.get(skill.name, {}) or {}
        required = extract_required_inputs(skill)
        missing = [n for n in required if n not in bindings or bindings[n] in (None, "")]
        if missing:
            missing_by_skill[skill.name] = missing

    if missing_by_skill:
        # Build a flat list for the error message and a structured
        # mapping for programmatic consumers.
        flat: list[str] = []
        for skill_name, names in missing_by_skill.items():
            flat.extend(f"{skill_name}.{n}" for n in names)
        raise SkillInputMissing(
            f"Required skill inputs are missing: {', '.join(flat)}",
            details={
                "missing": flat,
                "missing_by_skill": missing_by_skill,
            },
        )

    # 2) Render each skill with its bindings applied. The Organization
    #    Profile (D4) leads the section list when at least one attached
    #    skill consumes it; rendering it through the same path as
    #    skills means it picks up the same header / formatting / input
    #    substitution treatment without a special-case codepath.
    rendered: list[_AssembledSkill] = []
    if organization_profile is not None and any(consumes_organization_profile(s) for s in skills):
        # Profile uses no caller-supplied inputs (its content is the
        # operator-edited Markdown body); pass an empty bindings dict.
        rendered.append(_render_skill(organization_profile, inputs={}))
    for skill in skills:
        bindings = skill_inputs.get(skill.name, {}) or {}
        rendered.append(_render_skill(skill, inputs=bindings))

    skill_block = _SKILL_SEPARATOR.join(r.text for r in rendered)

    # 3) Merge with an existing system message, if present.
    if existing_system_message and existing_system_message.strip():
        return f"{skill_block}{_PREPEND_SEPARATOR}{existing_system_message.strip()}"
    return skill_block
