"""Unit tests for the C7 project schemas, helpers, and constraints.

Pure-Python tests (no DB, no HTTP). Cover:

* ``slugify`` — edge cases (empty, all-non-ascii, length cap, etc.).
* ``ProjectCreateRequest`` — privileged-implies-tier rule, context cap,
  slug pattern.
* ``ProjectUpdateRequest`` — partial update semantics, no privileged
  rule on PATCH (validated in handler).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.projects import (
    CONTEXT_MD_MAX_BYTES,
    SLUG_MAX_LEN,
    SLUG_RE,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    slugify,
)

# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slugify_basic() -> None:
    assert slugify("Acme MSA Renewal") == "acme-msa-renewal"


@pytest.mark.unit
def test_slugify_handles_punctuation() -> None:
    assert slugify("Foo, Bar & Baz!") == "foo-bar-baz"


@pytest.mark.unit
def test_slugify_handles_double_dashes() -> None:
    assert slugify("hello   world") == "hello-world"


@pytest.mark.unit
def test_slugify_strips_leading_trailing_dashes() -> None:
    assert slugify("  hello  ") == "hello"
    assert slugify("---hello---") == "hello"


@pytest.mark.unit
def test_slugify_handles_unicode_by_dropping_it() -> None:
    # Non-ASCII codepoints don't survive the regex; `naïve` -> `na-ve`.
    assert slugify("naïve résumé") == "na-ve-r-sum"


@pytest.mark.unit
def test_slugify_returns_default_for_empty_input() -> None:
    assert slugify("") == "project"
    assert slugify("!!!") == "project"


@pytest.mark.unit
def test_slugify_truncates_to_slug_max_len() -> None:
    long = "a" * (SLUG_MAX_LEN + 50)
    out = slugify(long)
    assert len(out) <= SLUG_MAX_LEN
    assert SLUG_RE.match(out)


@pytest.mark.unit
def test_slugify_output_matches_slug_re() -> None:
    """Every slugify output must satisfy SLUG_RE."""

    samples = [
        "Acme MSA",
        "  hello  ",
        "naïve résumé",
        "a" * 200,
        "!!!",
        "Foo, Bar & Baz!",
    ]
    for s in samples:
        assert SLUG_RE.match(slugify(s)), f"slugify({s!r}) violated SLUG_RE"


# ---------------------------------------------------------------------------
# ProjectCreateRequest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_request_minimal() -> None:
    req = ProjectCreateRequest(name="Test")
    assert req.name == "Test"
    assert req.privileged is False
    assert req.minimum_inference_tier is None


@pytest.mark.unit
def test_create_request_strips_whitespace_from_name() -> None:
    req = ProjectCreateRequest(name="   Test   ")
    assert req.name == "Test"


@pytest.mark.unit
def test_create_request_rejects_empty_name() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="")


@pytest.mark.unit
def test_create_request_rejects_too_long_name() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="a" * 201)


@pytest.mark.unit
def test_create_request_rejects_invalid_slug_pattern() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="Test", slug="Bad Slug!")


@pytest.mark.unit
def test_create_request_accepts_valid_slug() -> None:
    req = ProjectCreateRequest(name="Test", slug="my-project-2")
    assert req.slug == "my-project-2"


@pytest.mark.unit
def test_create_request_privileged_without_tier_raises() -> None:
    with pytest.raises(PydanticValidationError) as ei:
        ProjectCreateRequest(name="X", privileged=True)
    assert "minimum_inference_tier" in str(ei.value)


@pytest.mark.unit
def test_create_request_privileged_with_tier_accepted() -> None:
    req = ProjectCreateRequest(name="X", privileged=True, minimum_inference_tier=2)
    assert req.privileged is True
    assert req.minimum_inference_tier == 2


@pytest.mark.unit
def test_create_request_rejects_invalid_tier() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="X", privileged=True, minimum_inference_tier=6)  # type: ignore[arg-type]  # intentionally invalid


@pytest.mark.unit
def test_create_request_rejects_oversized_context_md() -> None:
    big = "X" * (CONTEXT_MD_MAX_BYTES + 1)
    with pytest.raises(PydanticValidationError) as ei:
        ProjectCreateRequest(name="X", context_md=big)
    assert "context_md" in str(ei.value)


@pytest.mark.unit
def test_create_request_accepts_max_size_context_md() -> None:
    big = "X" * CONTEXT_MD_MAX_BYTES
    req = ProjectCreateRequest(name="X", context_md=big)
    assert len(req.context_md or "") == CONTEXT_MD_MAX_BYTES


@pytest.mark.unit
def test_create_request_context_md_byte_count_not_codepoint() -> None:
    """The cap is in UTF-8 bytes, not codepoints."""

    # 'é' is 2 bytes in UTF-8; if we encoded `CONTEXT_MD_MAX_BYTES // 2 + 1`
    # 'é' chars we'd be over the byte cap.
    over = "é" * (CONTEXT_MD_MAX_BYTES // 2 + 1)
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="X", context_md=over)


@pytest.mark.unit
def test_create_request_forbids_extra_fields() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="X", unknown_field=42)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ProjectUpdateRequest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_request_all_optional() -> None:
    """Empty body is valid — PATCH with nothing is a no-op."""

    req = ProjectUpdateRequest()
    dumped = req.model_dump(exclude_unset=True)
    assert dumped == {}


@pytest.mark.unit
def test_update_request_distinguishes_unset_from_explicit_null() -> None:
    """exclude_unset preserves the unset/null distinction the handler relies on."""

    req_unset = ProjectUpdateRequest(name="Renamed")
    assert req_unset.model_dump(exclude_unset=True) == {"name": "Renamed"}

    req_clear_tier = ProjectUpdateRequest(minimum_inference_tier=None)
    dumped = req_clear_tier.model_dump(exclude_unset=True)
    assert "minimum_inference_tier" in dumped
    assert dumped["minimum_inference_tier"] is None


@pytest.mark.unit
def test_update_request_does_not_enforce_privileged_rule() -> None:
    """PATCH skips the privileged-implies-tier check; the handler does it."""

    # This would fail at the create layer; on PATCH it's fine because the
    # check has to be against the merged state.
    req = ProjectUpdateRequest(privileged=True)
    assert req.privileged is True
    assert req.minimum_inference_tier is None


@pytest.mark.unit
def test_update_request_rejects_invalid_slug() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectUpdateRequest(slug="Invalid Slug!")


@pytest.mark.unit
def test_update_request_rejects_oversized_context() -> None:
    with pytest.raises(PydanticValidationError):
        ProjectUpdateRequest(context_md="X" * (CONTEXT_MD_MAX_BYTES + 1))


@pytest.mark.unit
def test_update_request_archived_field_supported() -> None:
    req = ProjectUpdateRequest(archived=True)
    assert req.archived is True
    assert "archived" in req.model_dump(exclude_unset=True)
