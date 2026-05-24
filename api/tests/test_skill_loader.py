"""Unit tests for the C1 skill loader and registry.

Covers the in-memory side of the C1 surface — the filesystem walk,
frontmatter parse, schema validation, registry construction, lazy
reference-file loading, atomic-swap reload, and the SIGHUP wiring.
The HTTP endpoints are exercised in ``test_skill_endpoints.py``.

Test fixtures live under ``api/tests/fixtures/skills/`` (well-formed
fixtures) and ``api/tests/fixtures/skills_with_bad/`` (malformed fixtures
mixed with one well-formed sibling — to assert that one bad apple does
not spoil the whole startup). The fixtures contain synthetic content
with no legal substance; real skills under ``skills/`` are the
human-attestation pipeline's domain (per CLAUDE.md and
``skills/CONTRIBUTING.md``), not test inputs.
"""

from __future__ import annotations

import signal
from pathlib import Path

import pytest

from app.skills import SkillRegistry, load_registry
from app.skills.loader import (
    _FRONTMATTER_RE,
    LoaderError,
    _load_one,
    install_sighup_reload,
)
from app.skills.registry import MutableSkillRegistry
from app.skills.schema import (
    LQAIFrontmatter,
    SkillFrontmatter,
    derive_summary,
    filter_summary_for_response,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _capture_loader_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture WARNING calls on the skill-loader logger by monkey-patching
    the module's ``log.warning`` method directly.

    Why not ``caplog``: the FastAPI lifespan calls ``logging.basicConfig()``
    in earlier suite tests (``app/main.py``); under pytest-asyncio's
    session-scoped loop, that interaction has empirically muted caplog
    in CI even when ``propagate=True`` and the logger's level is set
    explicitly (see commits 50c631f and 8d1fff5 — both attempts failed
    on CI while passing in isolation). Monkey-patching the bound
    ``warning`` method bypasses every layer of the logging stack, so the
    test is robust regardless of session-order state.

    Returns the rendered-message list; the caller asserts on its
    contents. ``monkeypatch`` undoes the patch at test teardown.
    """
    import app.skills.loader as loader_mod

    captured: list[str] = []
    original_warning = loader_mod.log.warning

    def _capture(msg: object, *args: object, **kwargs: object) -> None:
        # Render the format string with the printf-style args the loader
        # passes, so the test can grep for substrings like "missing-name".
        try:
            rendered = msg % args if args else str(msg)
        except (TypeError, ValueError):
            rendered = str(msg)
        captured.append(rendered)
        original_warning(msg, *args, **kwargs)

    monkeypatch.setattr(loader_mod.log, "warning", _capture)
    return captured


GOOD_FIXTURES = FIXTURES_DIR / "skills"
MIXED_FIXTURES = FIXTURES_DIR / "skills_with_bad"
REAL_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


# --- Schema tests ------------------------------------------------------------


@pytest.mark.unit
def test_frontmatter_minimal_valid() -> None:
    """Required fields only — `name` + `description`. `lq_ai:` defaults."""

    fm = SkillFrontmatter.model_validate({"name": "x", "description": "A minimal skill."})
    assert fm.name == "x"
    assert fm.description == "A minimal skill."
    assert isinstance(fm.lq_ai, LQAIFrontmatter)
    assert fm.lq_ai.tags == []


@pytest.mark.unit
def test_frontmatter_missing_name_rejected() -> None:
    """`name` is required; absence raises a Pydantic ValidationError."""

    from pydantic import ValidationError

    with pytest.raises(ValidationError) as info:
        SkillFrontmatter.model_validate({"description": "no name"})
    assert "name" in str(info.value)


@pytest.mark.unit
def test_frontmatter_missing_description_rejected() -> None:
    """`description` is required; absence raises a Pydantic ValidationError."""

    from pydantic import ValidationError

    with pytest.raises(ValidationError) as info:
        SkillFrontmatter.model_validate({"name": "x"})
    assert "description" in str(info.value)


@pytest.mark.unit
def test_frontmatter_unknown_top_level_field_allowed() -> None:
    """Permissive mode — unknown top-level fields are kept (not rejected).

    The M1 starter corpus uses fields the formal authoring guide does
    not document; the loader must accept them rather than reject the
    skill.
    """

    fm = SkillFrontmatter.model_validate(
        {
            "name": "x",
            "description": "Unknown field test.",
            "experimental": "true",
        }
    )
    assert fm.name == "x"


@pytest.mark.unit
def test_frontmatter_lq_ai_minimum_inference_tier_bounds() -> None:
    """`minimum_inference_tier` is bounded to 1..5 inclusive."""

    fm = SkillFrontmatter.model_validate(
        {
            "name": "x",
            "description": "Tier ok.",
            "lq_ai": {"minimum_inference_tier": 3},
        }
    )
    assert fm.lq_ai.minimum_inference_tier == 3

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SkillFrontmatter.model_validate(
            {
                "name": "x",
                "description": "Tier out of range.",
                "lq_ai": {"minimum_inference_tier": 7},
            }
        )


@pytest.mark.unit
def test_derive_summary_defaults_when_lq_ai_sparse() -> None:
    """Sparse frontmatter still produces a contract-conforming summary."""

    fm = SkillFrontmatter.model_validate({"name": "skill-creator", "description": "X."})
    summary = derive_summary("skill-creator", fm)
    # OpenAPI required: name, version, scope, title — must all be present.
    assert summary.name == "skill-creator"
    assert summary.version == "unversioned"
    assert summary.scope == "builtin"
    assert summary.title  # humanised from name when missing


@pytest.mark.unit
def test_derive_summary_promotes_author() -> None:
    """`lq_ai.author` is promoted to the SkillSummary wire shape (DE-316).

    The `skill.execute` OTel span reads `skill.author`; before DE-316 it
    was always None because `author` lived only on `LQAIFrontmatter` and
    was never copied onto the wire shape the registry resolves.
    """

    fm = SkillFrontmatter.model_validate(
        {
            "name": "nda-review",
            "description": "X.",
            "lq_ai": {"author": "LQ.AI Core Team"},
        }
    )
    summary = derive_summary("nda-review", fm)
    assert summary.author == "LQ.AI Core Team"


@pytest.mark.unit
def test_derive_summary_author_none_when_absent() -> None:
    """Sparse frontmatter leaves `author` None (dropped from the response)."""

    fm = SkillFrontmatter.model_validate({"name": "x", "description": "Y."})
    summary = derive_summary("x", fm)
    assert summary.author is None
    assert "author" not in filter_summary_for_response(summary)


@pytest.mark.unit
def test_filter_summary_drops_none_and_empty() -> None:
    """`None` values and empty tag lists are dropped from the wire shape."""

    fm = SkillFrontmatter.model_validate({"name": "x", "description": "Y."})
    summary = derive_summary("x", fm)
    payload = filter_summary_for_response(summary)
    assert "tags" not in payload  # empty list dropped
    assert "jurisdiction" not in payload  # None dropped
    assert payload["scope"] == "builtin"
    assert payload["name"] == "x"


@pytest.mark.unit
def test_frontmatter_regex_matches_canonical_header() -> None:
    """The regex anchors on a leading `---\\n...---\\n` exactly."""

    text = "---\nname: x\ndescription: y\n---\n# body\n"
    m = _FRONTMATTER_RE.match(text)
    assert m is not None
    assert m.group("yaml") == "name: x\ndescription: y"
    assert m.group("body").startswith("# body")


@pytest.mark.unit
def test_frontmatter_regex_rejects_no_delimiters() -> None:
    """A plain markdown file (no frontmatter) does not match."""

    text = "# Title\n\nNo frontmatter here.\n"
    assert _FRONTMATTER_RE.match(text) is None


# --- Loader tests ------------------------------------------------------------


@pytest.mark.unit
def test_load_registry_happy_path() -> None:
    """Loads every well-formed fixture and exposes deterministic ordering."""

    registry = load_registry(GOOD_FIXTURES)
    assert isinstance(registry, SkillRegistry)
    assert sorted(registry.names()) == [
        "alpha-test-skill",
        "beta-minimal",
        "gamma-tagged",
    ]


@pytest.mark.unit
def test_load_registry_skips_malformed_skills_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One malformed sibling does not break the rest of the registry."""

    captured = _capture_loader_warnings(monkeypatch)
    registry = load_registry(MIXED_FIXTURES)

    # Only the well-formed `good-skill` makes it into the registry.
    assert registry.names() == ["good-skill"]

    # Each malformed fixture surfaces a WARNING line.
    messages = " | ".join(captured)
    assert "missing-name" in messages
    assert "no-frontmatter" in messages
    assert "bad-yaml" in messages
    assert "wrong-name" in messages or "name/folder mismatch" in messages


@pytest.mark.unit
def test_load_registry_empty_dir_returns_empty_registry(tmp_path: Path) -> None:
    """Empty directory → empty registry, not a crash."""

    registry = load_registry(tmp_path)
    assert registry.names() == []


@pytest.mark.unit
def test_load_registry_nonexistent_dir_returns_empty_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pointing at a nonexistent path produces an empty registry + WARNING."""

    target = tmp_path / "does-not-exist"
    captured = _capture_loader_warnings(monkeypatch)
    registry = load_registry(target)
    assert registry.names() == []
    assert any("does not exist" in msg for msg in captured)


@pytest.mark.unit
def test_load_one_returns_record_with_paths(tmp_path: Path) -> None:
    """`_load_one` returns a record whose folder path matches the source."""

    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A demo skill for the test.\n---\n# Body\n"
    )
    (folder / "reference").mkdir()
    (folder / "reference" / "a.md").write_text("ref-a")
    (folder / "examples").mkdir()
    (folder / "examples" / "ex.md").write_text("ex-1")

    rec = _load_one(folder)
    assert rec.name == "demo"
    assert rec.folder == folder
    assert (folder / "reference" / "a.md") in rec.reference_paths
    assert (folder / "examples" / "ex.md") in rec.example_paths


@pytest.mark.unit
def test_load_one_rejects_missing_frontmatter(tmp_path: Path) -> None:
    """A SKILL.md without `---` delimiters raises LoaderError."""

    folder = tmp_path / "no-fm"
    folder.mkdir()
    (folder / "SKILL.md").write_text("# Body only\n")

    with pytest.raises(LoaderError) as info:
        _load_one(folder)
    assert "frontmatter" in str(info.value).lower()


@pytest.mark.unit
def test_load_real_skills_corpus_has_all_starter_skills() -> None:
    """The real `skills/` directory loads cleanly with the full starter set.

    Per the C1 verification step, every starter skill must round-trip
    through the loader. The exact count is asserted as a *lower bound*
    (>= 10) — the corpus may grow during M1 without breaking this test.
    """

    if not REAL_SKILLS_DIR.is_dir():
        pytest.skip(f"real skills directory not present: {REAL_SKILLS_DIR}")

    registry = load_registry(REAL_SKILLS_DIR)
    names = registry.names()
    assert len(names) >= 10, f"expected at least 10 starter skills; got {names}"
    # Spot-check a couple of skills we know are in the M1 corpus.
    assert "nda-review" in names
    assert "skill-creator" in names


# --- Registry / lazy materialisation tests -----------------------------------


@pytest.mark.unit
def test_summary_omits_body() -> None:
    """`SkillSummary` does not carry the body markdown."""

    registry = load_registry(GOOD_FIXTURES)
    summaries = registry.list_summaries()
    for s in summaries:
        # Pydantic models don't expose `content_md`; this is a typing
        # check rather than a runtime one — the test is here to pin
        # the contract via attribute access.
        assert not hasattr(s, "content_md")


@pytest.mark.unit
def test_full_skill_includes_reference_and_example_files() -> None:
    """`get_skill` materialises reference/ and examples/ contents lazily."""

    registry = load_registry(GOOD_FIXTURES)
    skill = registry.get_skill("alpha-test-skill")
    assert skill is not None
    ref_paths = {f.path for f in skill.reference_files}
    assert "reference/note.md" in ref_paths
    ex_paths = {f.path for f in skill.example_files}
    assert "examples/basic.md" in ex_paths


@pytest.mark.unit
def test_get_skill_returns_none_for_unknown_name() -> None:
    """Unknown name → None (the API handler turns this into a 404)."""

    registry = load_registry(GOOD_FIXTURES)
    assert registry.get_skill("never-existed") is None


@pytest.mark.unit
def test_list_summaries_filters_by_tag() -> None:
    """`tag` filter is case-insensitive and selects only matching skills."""

    registry = load_registry(GOOD_FIXTURES)
    matched = registry.list_summaries(tag="special-tag")
    assert [s.name for s in matched] == ["gamma-tagged"]
    # Case-insensitive
    matched_upper = registry.list_summaries(tag="SPECIAL-TAG")
    assert [s.name for s in matched_upper] == ["gamma-tagged"]


# --- Atomic swap tests -------------------------------------------------------


@pytest.mark.unit
def test_mutable_registry_swap_returns_old_snapshot(tmp_path: Path) -> None:
    """`replace` swaps in the new registry and returns the prior one."""

    initial = load_registry(GOOD_FIXTURES)
    holder = MutableSkillRegistry(initial)
    assert holder.current() is initial

    new = load_registry(tmp_path)  # empty
    old = holder.replace(new)
    assert old is initial
    assert holder.current() is new
    assert holder.current().names() == []


@pytest.mark.unit
def test_in_flight_reader_sees_consistent_snapshot(tmp_path: Path) -> None:
    """A reader that captures `current()` is unaffected by a subsequent swap.

    Models the "request handler reads holder.current() and operates on
    that snapshot" pattern. The atomic-swap design says: once the
    handler has the snapshot reference, any concurrent swap doesn't
    change what the handler observes.
    """

    initial = load_registry(GOOD_FIXTURES)
    holder = MutableSkillRegistry(initial)

    # Reader captures the snapshot.
    snapshot = holder.current()
    snapshot_names_before = list(snapshot.names())

    # Concurrent swap.
    holder.replace(load_registry(tmp_path))

    # Reader still sees the original snapshot's contents.
    assert list(snapshot.names()) == snapshot_names_before
    # And the holder reflects the new state for *new* readers.
    assert holder.current().names() == []


# --- SIGHUP wiring tests -----------------------------------------------------


@pytest.mark.unit
def test_install_sighup_reload_replaces_signal_handler(tmp_path: Path) -> None:
    """SIGHUP installs a real handler when SIGHUP is available on the platform."""

    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")

    initial = load_registry(GOOD_FIXTURES)
    holder = MutableSkillRegistry(initial)
    prior = signal.getsignal(signal.SIGHUP)
    try:
        install_sighup_reload(holder, GOOD_FIXTURES)
        installed = signal.getsignal(signal.SIGHUP)
        assert installed is not None
        assert installed is not prior or installed != prior
    finally:
        # Restore whatever was there before so the global state isn't
        # leaked across the test session.
        signal.signal(signal.SIGHUP, prior if prior is not None else signal.SIG_DFL)


@pytest.mark.unit
def test_install_sighup_reload_handler_swaps_registry(tmp_path: Path) -> None:
    """Invoking the installed handler swaps the holder's registry.

    We invoke the handler by calling it directly rather than sending a
    real SIGHUP — the latter is exercised in
    ``test_skill_sighup_reload.py`` against a real subprocess. The
    direct invocation here pins the swap behaviour as a unit test.
    """

    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")

    # Start with the empty fixture; reload from the real fixtures dir.
    initial = load_registry(tmp_path)
    holder = MutableSkillRegistry(initial)
    prior = signal.getsignal(signal.SIGHUP)
    try:
        install_sighup_reload(holder, GOOD_FIXTURES)
        handler = signal.getsignal(signal.SIGHUP)
        assert callable(handler)
        # The handler signature is (signum, frame).
        handler(signal.SIGHUP, None)  # type: ignore[arg-type, misc]
        new_registry = holder.current()
        assert new_registry is not initial
        assert "alpha-test-skill" in new_registry.names()
    finally:
        signal.signal(signal.SIGHUP, prior if prior is not None else signal.SIG_DFL)
