"""Unit tests for the skill prompt assembler (C2).

Pure-function tests; no I/O. Covers:

* :func:`interpolate` — substitution semantics.
* :func:`extract_required_inputs` — parsing the verbatim frontmatter
  for the ``inputs.required`` block.
* :func:`assemble_skill_prompt` — body + references + input bindings,
  multi-skill concatenation, system-message merging, missing-required-
  input error path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.clients.backend import Skill, SkillFile
from app.errors import SkillInputMissing
from app.skills.assembler import (
    assemble_skill_prompt,
    consumes_organization_profile,
    extract_required_inputs,
    interpolate,
)

# --- interpolate -------------------------------------------------------------


@pytest.mark.unit
def test_interpolate_substitutes_known_variable() -> None:
    assert interpolate("hello {{name}}", {"name": "Ada"}) == "hello Ada"


@pytest.mark.unit
def test_interpolate_with_whitespace_inside_braces() -> None:
    assert interpolate("hello {{ name }}", {"name": "Ada"}) == "hello Ada"


@pytest.mark.unit
def test_interpolate_leaves_unknown_variables_in_place() -> None:
    assert interpolate("hi {{stranger}}", {}) == "hi {{stranger}}"


@pytest.mark.unit
def test_interpolate_tolerates_extra_bindings() -> None:
    assert interpolate("hi", {"unused": "x"}) == "hi"


@pytest.mark.unit
def test_interpolate_renders_non_strings() -> None:
    assert interpolate("count={{n}}", {"n": 42}) == "count=42"
    assert interpolate("flag={{b}}", {"b": True}) == "flag=True"


@pytest.mark.unit
def test_interpolate_renders_none_as_empty_string() -> None:
    assert interpolate("opt={{x}}", {"x": None}) == "opt="


@pytest.mark.unit
def test_interpolate_does_not_evaluate_expressions() -> None:
    """No template-injection surface — `{{x.y}}` is not a substitution."""

    assert interpolate("{{x.y}}", {"x": "should not match"}) == "{{x.y}}"


@pytest.mark.unit
def test_interpolate_does_not_chain_substitutions() -> None:
    """Substituted values are NOT re-scanned for placeholders.

    A value of ``"{{evil}}"`` should appear verbatim in the output, not
    trigger a second-pass substitution. This matters because skill inputs
    are user-provided text — chained substitution would be a
    template-injection vector.
    """

    out = interpolate("user said: {{msg}}", {"msg": "{{secret}}", "secret": "leaked"})
    assert out == "user said: {{secret}}"


# --- extract_required_inputs -------------------------------------------------


def _skill_with_yaml(yaml_block: str) -> Skill:
    return Skill(
        name="alpha",
        content_md="body",
        content_yaml=yaml_block,
    )


@pytest.mark.unit
def test_extract_required_inputs_handles_M1_corpus_shape() -> None:
    """Matches the NDA-review-style frontmatter."""

    yaml_block = (
        "name: alpha\n"
        "description: ...\n"
        "lq_ai:\n"
        "  title: Alpha\n"
        "inputs:\n"
        "  required:\n"
        "    - name: document\n"
        "      type: document\n"
        "    - name: perspective\n"
        "      type: text\n"
        "  optional:\n"
        "    - name: jurisdiction\n"
        "      type: text\n"
    )
    skill = _skill_with_yaml(yaml_block)
    assert extract_required_inputs(skill) == ["document", "perspective"]


@pytest.mark.unit
def test_extract_required_inputs_handles_simple_string_list() -> None:
    """Some skills could declare required: [a, b] without nesting."""

    yaml_block = "inputs:\n  required:\n    - foo\n    - bar\n"
    skill = _skill_with_yaml(yaml_block)
    assert extract_required_inputs(skill) == ["foo", "bar"]


@pytest.mark.unit
def test_extract_required_inputs_returns_empty_when_no_inputs() -> None:
    skill = _skill_with_yaml("name: alpha\ndescription: x\n")
    assert extract_required_inputs(skill) == []


@pytest.mark.unit
def test_extract_required_inputs_returns_empty_on_malformed_yaml() -> None:
    skill = _skill_with_yaml("not: [valid yaml")  # mismatched bracket
    assert extract_required_inputs(skill) == []


@pytest.mark.unit
def test_extract_required_inputs_returns_empty_when_inputs_is_not_dict() -> None:
    yaml_block = "inputs: 42\n"
    skill = _skill_with_yaml(yaml_block)
    assert extract_required_inputs(skill) == []


# --- assemble_skill_prompt ---------------------------------------------------


def _basic_skill(name: str = "alpha", body: str = "Body") -> Skill:
    return Skill(
        name=name,
        version="1.0.0",
        scope="builtin",
        title=name.title(),
        description=f"A test skill named {name}",
        content_md=body,
        content_yaml=f"name: {name}\ndescription: ...\n",
    )


@pytest.mark.unit
def test_assemble_with_no_skills_returns_empty_string() -> None:
    assert assemble_skill_prompt([]) == ""


@pytest.mark.unit
def test_assemble_with_no_skills_preserves_existing_system_message() -> None:
    out = assemble_skill_prompt([], existing_system_message="Be terse.")
    assert out == "Be terse."


@pytest.mark.unit
def test_assemble_single_skill_includes_body_and_metadata() -> None:
    skill = _basic_skill("alpha", body="# Workflow\n\n1. Step one")
    out = assemble_skill_prompt([skill])
    # The header includes the title and version.
    assert "# Skill: Alpha (v1.0.0)" in out
    # The description is included.
    assert "A test skill named alpha" in out
    # The body markdown is there.
    assert "Workflow" in out


@pytest.mark.unit
def test_assemble_unversioned_skill_omits_version_in_header() -> None:
    skill = Skill(
        name="alpha",
        version="unversioned",
        title="Alpha",
        content_md="body",
        content_yaml="name: alpha\n",
    )
    out = assemble_skill_prompt([skill])
    assert "# Skill: Alpha" in out
    # No "(vunversioned)" or similar.
    assert "(v" not in out


@pytest.mark.unit
def test_assemble_substitutes_inputs_into_body() -> None:
    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Review {{document}} from {{perspective}}.",
        content_yaml="name: alpha\n",
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={"alpha": {"document": "the NDA", "perspective": "discloser"}},
    )
    assert "Review the NDA from discloser." in out


@pytest.mark.unit
def test_assemble_substitutes_inputs_into_reference_files() -> None:
    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Body",
        content_yaml="name: alpha\n",
        reference_files=[
            SkillFile(
                path="reference/note.md",
                content="For counterparty {{counterparty}}, see ...",
            )
        ],
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={"alpha": {"counterparty": "Acme Corp"}},
    )
    assert "For counterparty Acme Corp" in out
    assert "## Reference: reference/note.md" in out


@pytest.mark.unit
def test_assemble_includes_reference_files_in_separate_blocks() -> None:
    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Body content here",
        content_yaml="name: alpha\n",
        reference_files=[
            SkillFile(path="reference/a.md", content="ref a"),
            SkillFile(path="reference/b.md", content="ref b"),
        ],
    )
    out = assemble_skill_prompt([skill])
    assert "## Reference: reference/a.md" in out
    assert "## Reference: reference/b.md" in out
    assert "ref a" in out
    assert "ref b" in out


# --- DE-328: unconsumed inputs surfaced as a labelled block ------------------


@pytest.mark.unit
def test_assemble_surfaces_unconsumed_inputs_for_non_templated_skill() -> None:
    """A non-templated body (no ``{{}}``) must not silently drop bound inputs.

    None of the built-in skills use ``{{placeholder}}`` tokens, so without
    DE-328 (Option A) the caller-bound inputs vanish before reaching the
    model. The assembled prompt must carry each leftover input's name AND
    value under a "Provided inputs" block.
    """

    skill = Skill(
        name="comms-improver",
        title="Comms Improver",
        content_md="Improve the writing. No placeholders here.",
        content_yaml="name: comms-improver\n",
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={
            "comms-improver": {
                "audience": "executives",
                "text": "Our Q3 results",
            }
        },
    )
    assert "### Provided inputs for Comms Improver" in out
    assert "audience" in out
    assert "executives" in out
    assert "text" in out
    assert "Our Q3 results" in out


@pytest.mark.unit
def test_assemble_does_not_duplicate_consumed_templated_inputs() -> None:
    """An input consumed by ``{{}}`` is substituted in-body, not re-listed.

    A templated skill whose inputs are all consumed must get NO "Provided
    inputs" block, so the value isn't duplicated (once in-body, once in the
    block).
    """

    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Review {{document}} carefully.",
        content_yaml="name: alpha\n",
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={"alpha": {"document": "the NDA"}},
    )
    assert "Review the NDA carefully." in out
    assert "Provided inputs" not in out


@pytest.mark.unit
def test_assemble_block_only_lists_unconsumed_inputs() -> None:
    """Mixed case: consumed inputs substitute in-body; only leftovers list."""

    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Review {{document}} now.",
        content_yaml="name: alpha\n",
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={"alpha": {"document": "the NDA", "audience": "the board"}},
    )
    assert "Review the NDA now." in out
    assert "### Provided inputs for Alpha" in out
    assert "audience" in out
    assert "the board" in out
    # The consumed input is not duplicated in the block.
    assert out.count("the NDA") == 1


@pytest.mark.unit
def test_assemble_omits_empty_value_inputs_from_block() -> None:
    """Leftover inputs whose value is None/empty-string are not listed."""

    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="No placeholders.",
        content_yaml="name: alpha\n",
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={"alpha": {"audience": "execs", "blank": "", "missing": None}},
    )
    assert "### Provided inputs for Alpha" in out
    assert "audience: execs" in out
    assert "blank" not in out
    assert "missing" not in out


@pytest.mark.unit
def test_interpolate_records_consumed_keys() -> None:
    """The optional ``consumed`` out-param tracks substituted keys only."""

    consumed: set[str] = set()
    out = interpolate("hi {{name}}", {"name": "Ada", "unused": "x"}, consumed=consumed)
    assert out == "hi Ada"
    assert consumed == {"name"}


@pytest.mark.unit
def test_assemble_input_consumed_only_in_reference_is_not_relisted() -> None:
    """A key consumed by a ``{{}}`` in a reference file (not the body) must not
    reappear in the "Provided inputs" block — consumed-tracking unions the body
    and every reference file, not just the body.
    """

    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="No body placeholders.",
        content_yaml="name: alpha\n",
        reference_files=[
            SkillFile(
                path="reference/note.md",
                content="For counterparty {{counterparty}}, proceed.",
            )
        ],
    )
    out = assemble_skill_prompt(
        [skill],
        skill_inputs={"alpha": {"counterparty": "Acme Corp"}},
    )
    # Substituted in the reference...
    assert "For counterparty Acme Corp" in out
    # ...and therefore NOT re-listed in a Provided-inputs block.
    assert "Provided inputs" not in out
    assert out.count("Acme Corp") == 1


@pytest.mark.unit
def test_assemble_provided_inputs_blocks_do_not_bleed_across_skills() -> None:
    """Each skill's leftover-input block lists only that skill's bindings.

    ``_render_skill`` scopes ``consumed``/``inputs`` per skill, so a multi-skill
    assemble must keep each "Provided inputs" block under its own skill section
    with no cross-skill bleed.
    """

    alpha = Skill(
        name="alpha",
        title="Alpha",
        content_md="Alpha body, no placeholders.",
        content_yaml="name: alpha\n",
    )
    beta = Skill(
        name="beta",
        title="Beta",
        content_md="Beta body, no placeholders.",
        content_yaml="name: beta\n",
    )
    out = assemble_skill_prompt(
        [alpha, beta],
        skill_inputs={
            "alpha": {"audience": "the board"},
            "beta": {"jurisdiction": "Delaware"},
        },
    )
    assert "### Provided inputs for Alpha" in out
    assert "### Provided inputs for Beta" in out
    # Each value appears exactly once, under its own skill's block.
    assert out.count("the board") == 1
    assert out.count("Delaware") == 1
    # Alpha's block precedes Beta's, and alpha's input is above the beta divider.
    alpha_block = out.index("### Provided inputs for Alpha")
    beta_header = out.index("# Skill: Beta")
    assert alpha_block < beta_header
    assert out.index("the board") < beta_header


@pytest.mark.unit
def test_assemble_concatenates_multiple_skills_with_separator() -> None:
    a = _basic_skill("alpha", body="Alpha body")
    b = _basic_skill("beta", body="Beta body")
    out = assemble_skill_prompt([a, b])
    assert "Alpha body" in out
    assert "Beta body" in out
    # The separator divider is between them.
    alpha_idx = out.index("Alpha body")
    beta_idx = out.index("Beta body")
    assert alpha_idx < beta_idx
    between = out[alpha_idx:beta_idx]
    assert "---" in between


@pytest.mark.unit
def test_assemble_preserves_skill_order() -> None:
    a = _basic_skill("alpha", body="A first")
    b = _basic_skill("beta", body="B second")
    out_ab = assemble_skill_prompt([a, b])
    out_ba = assemble_skill_prompt([b, a])
    assert out_ab.index("A first") < out_ab.index("B second")
    assert out_ba.index("B second") < out_ba.index("A first")


@pytest.mark.unit
def test_assemble_prepends_to_existing_system_message() -> None:
    skill = _basic_skill("alpha", body="Skill body")
    out = assemble_skill_prompt(
        [skill],
        existing_system_message="Operator-specific instructions go here.",
    )
    skill_idx = out.index("Skill body")
    operator_idx = out.index("Operator-specific instructions")
    assert skill_idx < operator_idx
    # The separator includes a clear marker.
    assert "Operator system instructions" in out


@pytest.mark.unit
def test_assemble_ignores_empty_existing_system_message() -> None:
    skill = _basic_skill("alpha", body="Skill body")
    out = assemble_skill_prompt([skill], existing_system_message="")
    assert "Skill body" in out
    assert "Operator system instructions" not in out


@pytest.mark.unit
def test_assemble_ignores_whitespace_only_existing_system_message() -> None:
    skill = _basic_skill("alpha", body="Skill body")
    out = assemble_skill_prompt([skill], existing_system_message="   \n\t  ")
    assert "Operator system instructions" not in out


@pytest.mark.unit
def test_assemble_raises_on_missing_required_input() -> None:
    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Review {{document}}",
        content_yaml=(
            "name: alpha\ndescription: ...\n"
            "inputs:\n  required:\n    - name: document\n      type: document\n"
        ),
    )
    with pytest.raises(SkillInputMissing) as exc_info:
        assemble_skill_prompt([skill])
    assert "alpha.document" in exc_info.value.details["missing"]


@pytest.mark.unit
def test_assemble_raises_when_required_input_is_empty_string() -> None:
    """Empty-string input is treated as missing — nothing was bound."""

    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Review {{document}}",
        content_yaml=(
            "name: alpha\ndescription: ...\n"
            "inputs:\n  required:\n    - name: document\n      type: document\n"
        ),
    )
    with pytest.raises(SkillInputMissing):
        assemble_skill_prompt([skill], skill_inputs={"alpha": {"document": ""}})


@pytest.mark.unit
def test_assemble_aggregates_missing_inputs_across_skills() -> None:
    """One error names every missing field across all attached skills."""

    a = Skill(
        name="alpha",
        title="Alpha",
        content_md="x",
        content_yaml=("inputs:\n  required:\n    - name: doc_a\n"),
    )
    b = Skill(
        name="beta",
        title="Beta",
        content_md="x",
        content_yaml=("inputs:\n  required:\n    - name: doc_b\n"),
    )
    with pytest.raises(SkillInputMissing) as exc_info:
        assemble_skill_prompt([a, b])
    missing = exc_info.value.details["missing"]
    assert "alpha.doc_a" in missing
    assert "beta.doc_b" in missing


@pytest.mark.unit
def test_assemble_optional_input_not_supplied_leaves_placeholder() -> None:
    """Optional inputs without bindings leave the placeholder in place."""

    skill = Skill(
        name="alpha",
        title="Alpha",
        content_md="Optional: {{maybe}}",
        content_yaml=("inputs:\n  optional:\n    - name: maybe\n"),
    )
    out = assemble_skill_prompt([skill])
    # No raise — and the literal placeholder is preserved.
    assert "{{maybe}}" in out


@pytest.mark.unit
def test_assemble_per_skill_input_scoping_avoids_collisions() -> None:
    """Two skills with same-named variables don't collide.

    Skill A's ``{{x}}`` is bound from skill_inputs["alpha"]; skill B's
    ``{{x}}`` is bound from skill_inputs["beta"]. They can have
    different values.
    """

    a = Skill(
        name="alpha",
        title="Alpha",
        content_md="A says {{x}}",
        content_yaml="name: alpha\n",
    )
    b = Skill(
        name="beta",
        title="Beta",
        content_md="B says {{x}}",
        content_yaml="name: beta\n",
    )
    out = assemble_skill_prompt(
        [a, b],
        skill_inputs={"alpha": {"x": "alpha-value"}, "beta": {"x": "beta-value"}},
    )
    assert "A says alpha-value" in out
    assert "B says beta-value" in out


# --- consumes_organization_profile + Organization Profile assembly (D4) -----


def _profile_skill(body: str = "Always cite Delaware as choice of law.") -> Skill:
    """The Skill-shaped Profile payload the backend's internal endpoint
    synthesizes — top-level ``use_organization_profile: false`` so the
    assembler never recursively re-prepends the Profile to itself."""

    return Skill(
        name="organization-profile",
        version="v1",
        scope="builtin",
        title="Organization Profile",
        content_md=body,
        content_yaml=(
            "name: organization-profile\n"
            "lq_ai:\n"
            "  is_organization_profile: true\n"
            "  use_organization_profile: false\n"
        ),
    )


@pytest.mark.unit
def test_consumes_org_profile_default_true_when_unset() -> None:
    """A skill with no ``use_organization_profile`` opts in by default.

    PRD §3.12 makes the Profile opt-in; opt-out requires an explicit
    ``false`` so the cautious read of an undeclared skill is "the
    operator wants their org voice applied here."
    """

    skill = _skill_with_yaml("name: alpha\nlq_ai:\n  title: Alpha\n")
    assert consumes_organization_profile(skill) is True


@pytest.mark.unit
def test_consumes_org_profile_false_when_lq_ai_block_opts_out() -> None:
    skill = _skill_with_yaml("name: alpha\nlq_ai:\n  use_organization_profile: false\n")
    assert consumes_organization_profile(skill) is False


@pytest.mark.unit
def test_consumes_org_profile_false_when_top_level_opts_out() -> None:
    """The synthesized Profile YAML carries the flag at the top level."""

    skill = _skill_with_yaml("name: organization-profile\nuse_organization_profile: false\n")
    assert consumes_organization_profile(skill) is False


@pytest.mark.unit
def test_consumes_org_profile_treats_malformed_yaml_as_opt_in() -> None:
    skill = _skill_with_yaml("not: [valid yaml")
    assert consumes_organization_profile(skill) is True


@pytest.mark.unit
def test_assemble_includes_profile_when_skill_consumes_it() -> None:
    """Profile body lands in the assembled prompt before the skill."""

    skill = _basic_skill()
    profile = _profile_skill("Use Delaware as default choice of law.")
    out = assemble_skill_prompt([skill], organization_profile=profile)
    assert "Use Delaware as default choice of law." in out
    # Profile leads the assembled section list — its position in the
    # string is before the skill body.
    assert out.index("Use Delaware") < out.index("Body")


@pytest.mark.unit
def test_assemble_omits_profile_when_all_skills_opt_out() -> None:
    """Skills explicitly setting opt-out keep the Profile out of the prompt."""

    skill = Skill(
        name="opt-out-skill",
        title="Opt Out",
        content_md="Skill body — no profile please",
        content_yaml="name: opt-out-skill\nlq_ai:\n  use_organization_profile: false\n",
    )
    profile = _profile_skill("Should not appear.")
    out = assemble_skill_prompt([skill], organization_profile=profile)
    assert "Should not appear." not in out
    assert "Skill body — no profile please" in out


@pytest.mark.unit
def test_assemble_omits_profile_when_none_passed() -> None:
    """No Profile set on the deployment → assembled output unchanged."""

    skill = _basic_skill()
    out_with = assemble_skill_prompt([skill], organization_profile=None)
    out_without = assemble_skill_prompt([skill])
    assert out_with == out_without


@pytest.mark.unit
def test_assemble_includes_profile_when_at_least_one_skill_opts_in() -> None:
    """Mixed opt-in / opt-out: Profile appears once at the top.

    The operator's intent (Profile is set) wins when *any* attached
    skill consumes it. We could implement per-skill toggling later, but
    a single system-prompt block is one shared context — toggling part
    of it on a per-section basis isn't meaningful at the LLM API level.
    """

    opt_in = _basic_skill(name="alpha", body="Alpha body")
    opt_out = Skill(
        name="beta",
        title="Beta",
        content_md="Beta body",
        content_yaml="name: beta\nlq_ai:\n  use_organization_profile: false\n",
    )
    profile = _profile_skill("Org-wide voice.")
    out = assemble_skill_prompt([opt_in, opt_out], organization_profile=profile)
    assert "Org-wide voice." in out
    # Exactly one Profile section, not one per consuming skill — the
    # current implementation prepends once and the test pins that
    # contract so a future "repeat per skill" change is a deliberate
    # signal, not an accidental token-count regression.
    assert out.count("Org-wide voice.") == 1


@pytest.mark.unit
def test_assemble_with_no_skills_ignores_profile() -> None:
    """Profile only fires when skills are attached.

    A bare chat with no skills shouldn't get an unsolicited org-prompt
    injected — the Profile is meta about how skills should behave, not
    a default system prompt.
    """

    profile = _profile_skill("Should not appear.")
    out = assemble_skill_prompt([], organization_profile=profile)
    assert out == ""


# --- required inputs nested under ``lq_ai:`` ---------------------------------


_NDA_REVIEW_SHAPED_YAML = (
    "name: nda-review\n"
    "lq_ai:\n"
    "  title: NDA Review\n"
    "  inputs:\n"
    "    required:\n"
    "      - name: document\n"
    "        type: document\n"
    "      - name: perspective\n"
    "        type: text\n"
    "    optional:\n"
    "      - name: jurisdiction\n"
)


@pytest.mark.unit
def test_extract_required_inputs_reads_lq_ai_nested_block() -> None:
    """Every shipped SKILL.md nests ``inputs`` under ``lq_ai:``; it must count."""

    skill = Skill(name="nda-review", content_md="body", content_yaml=_NDA_REVIEW_SHAPED_YAML)
    assert extract_required_inputs(skill) == ["document", "perspective"]


@pytest.mark.unit
def test_assemble_enforces_required_inputs_nested_under_lq_ai() -> None:
    skill = Skill(name="nda-review", content_md="body", content_yaml=_NDA_REVIEW_SHAPED_YAML)
    with pytest.raises(SkillInputMissing) as excinfo:
        assemble_skill_prompt([skill], skill_inputs={"nda-review": {"document": "the NDA"}})
    assert excinfo.value.details["missing"] == ["nda-review.perspective"]


# --- Shipped corpus ----------------------------------------------------------
#
# ``extract_required_inputs`` read the top-level ``inputs:`` block only
# for the whole of M1-M4 while every built-in SKILL.md nests it under
# ``lq_ai:``, so enforcement silently never fired. These tests load the
# real files so the corpus and the enforcer cannot drift apart again.

_SHIPPED_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Required inputs each built-in skill declares. Update deliberately when a
# skill's interface changes — every caller that attaches the skill must
# bind these, or the gateway refuses the request (ADR 0007 §2).
_SHIPPED_REQUIRED_INPUTS: dict[str, list[str]] = {
    "action-items-from-client-alert": ["document"],
    "case-law-research": ["question"],
    "comms-improver": ["text", "audience"],
    "contract-qa": ["document", "question"],
    "contract-snapshot": [],
    "dpa-checklist-review": ["document", "regulatory_regime"],
    "enhance-prompt": ["raw_input"],
    "msa-review-commercial-purchase": ["document", "perspective"],
    "msa-review-saas": ["document", "perspective"],
    "msa-snapshot": [],
    "nda-review": ["document", "perspective"],
    "nda-snapshot": [],
    "playbook-easy-extract": ["document"],
    "skill-creator": [],
    "vendor-privacy-policy-first-pass": ["document"],
}


def _shipped_skill(name: str) -> Skill:
    text = (_SHIPPED_SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert match is not None, f"{name}/SKILL.md has no frontmatter"
    return Skill(name=name, content_md=match.group(2), content_yaml=match.group(1))


@pytest.mark.unit
def test_shipped_corpus_required_inputs_are_read() -> None:
    """Every built-in skill's nested ``lq_ai.inputs.required`` is what the enforcer sees."""

    on_disk = sorted(p.name for p in _SHIPPED_SKILLS_DIR.iterdir() if (p / "SKILL.md").exists())
    assert on_disk == sorted(_SHIPPED_REQUIRED_INPUTS), (
        "a built-in skill was added or removed — update _SHIPPED_REQUIRED_INPUTS"
    )
    for name in on_disk:
        assert extract_required_inputs(_shipped_skill(name)) == _SHIPPED_REQUIRED_INPUTS[name], name


@pytest.mark.unit
@pytest.mark.parametrize(
    "name", sorted(n for n, required in _SHIPPED_REQUIRED_INPUTS.items() if required)
)
def test_shipped_skill_with_required_inputs_refuses_empty_bindings(name: str) -> None:
    """Attaching a built-in skill without its required inputs is a 400, not a silent run."""

    with pytest.raises(SkillInputMissing) as excinfo:
        assemble_skill_prompt([_shipped_skill(name)], skill_inputs={})
    expected = [f"{name}.{n}" for n in _SHIPPED_REQUIRED_INPUTS[name]]
    assert excinfo.value.details["missing"] == expected


@pytest.mark.unit
def test_shipped_skill_assembles_once_required_inputs_are_bound() -> None:
    out = assemble_skill_prompt(
        [_shipped_skill("nda-review")],
        skill_inputs={"nda-review": {"document": "NDA text", "perspective": "recipient"}},
    )
    assert "### Provided inputs for" in out
    assert "NDA text" in out
