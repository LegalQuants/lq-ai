"""Wave D.2 / Task 2.4 — ``slash_alias`` Pydantic regex validation.

Pure-Pydantic unit tests for ``UserSkillCreate`` and ``UserSkillUpdate``.
No DB, no HTTP client — the regex is the entire surface under test.

Format: ``^/[a-z0-9-]{1,32}$`` (leading slash, then 1-32 lowercase
alphanumerics or hyphens). ``None`` is always accepted (the column is
nullable and the alias is opt-in).

Real model column names are ``display_name`` / ``body`` — the plan's
draft snippet used ``title`` / ``body_md`` which were corrected during
Task 1.2 NEEDS_CONTEXT resolution.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.api.user_skills import UserSkillCreate, UserSkillUpdate


def _base_payload(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "personal-nda",
        "display_name": "Personal NDA",
        "description": "My NDA workflow",
        "body": "You review NDAs.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# UserSkillCreate.slash_alias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias",
    [
        "/nda",
        "/n",
        "/abc-123",
        "/" + "a" * 32,  # boundary: 32 chars after slash
        "/0",
        "/a-b-c-d",
    ],
)
def test_create_accepts_valid_slash_alias(alias: str) -> None:
    model = UserSkillCreate(**_base_payload(slash_alias=alias))
    assert model.slash_alias == alias


@pytest.mark.parametrize(
    "alias",
    [
        "nda",  # missing leading slash
        "/",  # nothing after the slash
        "/NDA",  # uppercase rejected
        "/nda!",  # punctuation rejected
        "/nda/sub",  # nested slashes rejected
        "/-nda",  # rule allows it by regex; included to verify
        # behavior is *not* surprising — see assertion below
        "/" + "a" * 33,  # 33 chars after slash → over the 32 ceiling
        "/has space",  # whitespace rejected
        "//double",  # leading-slash duplicate rejected
        "/ndaé",  # non-ASCII rejected
    ],
)
def test_create_rejects_invalid_slash_alias(alias: str) -> None:
    # The "/-nda" case is technically allowed by the regex ``^/[a-z0-9-]{1,32}$``
    # so it should round-trip cleanly; pull it out of the rejection set.
    if alias == "/-nda":
        model = UserSkillCreate(**_base_payload(slash_alias=alias))
        assert model.slash_alias == alias
        return
    with pytest.raises(ValidationError):
        UserSkillCreate(**_base_payload(slash_alias=alias))


def test_create_accepts_none_slash_alias() -> None:
    model = UserSkillCreate(**_base_payload(slash_alias=None))
    assert model.slash_alias is None


def test_create_defaults_slash_alias_to_none() -> None:
    """When slash_alias is omitted entirely, the field defaults to None."""
    model = UserSkillCreate(**_base_payload())
    assert model.slash_alias is None


# ---------------------------------------------------------------------------
# UserSkillUpdate.slash_alias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alias", ["/nda", "/a-b-1", "/" + "a" * 32])
def test_update_accepts_valid_slash_alias(alias: str) -> None:
    model = UserSkillUpdate(slash_alias=alias)
    assert model.slash_alias == alias


@pytest.mark.parametrize(
    "alias",
    [
        "nda",
        "/NDA",
        "/nda!",
        "/" + "a" * 33,
    ],
)
def test_update_rejects_invalid_slash_alias(alias: str) -> None:
    with pytest.raises(ValidationError):
        UserSkillUpdate(slash_alias=alias)


def test_update_accepts_none_slash_alias() -> None:
    model = UserSkillUpdate(slash_alias=None)
    assert model.slash_alias is None
