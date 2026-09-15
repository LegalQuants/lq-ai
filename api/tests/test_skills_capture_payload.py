"""Wave D.2 / Task 2.4 — capture-payload shape for ``UserSkillCreate``.

Validates two carve-outs:

* ``source_message_id`` is accepted on create as a free-form opaque
  string. Per the plan it is *documentary only* — accepted at the API
  surface but not exposed on ``UserSkillResponse`` and not persisted to
  any DB column. (No model column ships in migration 0023; the value
  rides the create-time audit log instead.)
* ``forked_from`` is write-once: present on ``UserSkillCreate`` and
  absent from ``UserSkillUpdate``. The PATCH model must not accept it
  so the documentary lineage cannot be rewritten after creation.

Real model column names are ``display_name`` / ``body`` — the plan's
draft snippet used ``title`` / ``body_md``.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from app.api.user_skills import UserSkillCreate, UserSkillUpdate


class _Payload(TypedDict):
    slug: str
    display_name: str
    description: str
    body: str
    source_message_id: NotRequired[str]
    forked_from: NotRequired[str]


def _base_payload(
    *, source_message_id: str | None = None, forked_from: str | None = None
) -> _Payload:
    base: _Payload = {
        "slug": "personal-nda",
        "display_name": "Personal NDA",
        "description": "My NDA workflow",
        "body": "You review NDAs.",
    }
    if source_message_id is not None:
        base["source_message_id"] = source_message_id
    if forked_from is not None:
        base["forked_from"] = forked_from
    return base


# ---------------------------------------------------------------------------
# source_message_id — accepted on create
# ---------------------------------------------------------------------------


def test_create_accepts_source_message_id() -> None:
    model = UserSkillCreate(
        **_base_payload(source_message_id="00000000-0000-0000-0000-000000000123")
    )
    assert model.source_message_id == "00000000-0000-0000-0000-000000000123"


def test_create_source_message_id_defaults_to_none() -> None:
    model = UserSkillCreate(**_base_payload())
    assert model.source_message_id is None


def test_create_accepts_forked_from() -> None:
    model = UserSkillCreate(**_base_payload(forked_from="nda-review"))
    assert model.forked_from == "nda-review"


def test_create_forked_from_defaults_to_none() -> None:
    model = UserSkillCreate(**_base_payload())
    assert model.forked_from is None


# ---------------------------------------------------------------------------
# forked_from + source_message_id — write-once: NOT on UserSkillUpdate
# ---------------------------------------------------------------------------


def test_update_does_not_expose_forked_from() -> None:
    """PATCH must not accept forked_from — documentary lineage is write-once."""
    assert "forked_from" not in UserSkillUpdate.model_fields


def test_update_does_not_expose_source_message_id() -> None:
    """PATCH must not accept source_message_id — capture is a create-time only signal."""
    assert "source_message_id" not in UserSkillUpdate.model_fields
