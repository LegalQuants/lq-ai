"""Wave D.2 / Task 1.2 — assert UserSkill model exposes slash_alias + forked_from.

TDD anchor for migration 0023. Test uses the real ``UserSkill`` column
names (``body``, ``display_name``) rather than the plan's draft names
(``body_md``, ``title``) — see Task 1.2 NEEDS_CONTEXT resolution.
"""

from app.models.user_skill import UserSkill


def test_user_skill_has_slash_alias_and_forked_from_columns() -> None:
    us = UserSkill(
        scope="user",
        slug="x",
        display_name="x",
        description="x",
        body="x",
    )
    assert hasattr(us, "slash_alias")
    assert hasattr(us, "forked_from")
    assert us.slash_alias is None
    assert us.forked_from is None
