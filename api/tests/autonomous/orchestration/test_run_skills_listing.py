"""A run profile's orchestrator skill is not offered in the skill picker (ADR 0038 D3).

The fictional profile's orchestrator is an installed skill. It plans and combines
for a governed run and does nothing useful attached to an ordinary message, so the
catalogue listing and the composer's autocomplete leave it out. New harness is
instructed by prompt files, which are not skills at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from app.api.skills import _run_orchestrator_skills
from app.autonomous.orchestration.profiles import registered_profiles
from app.main import app

pytestmark = pytest.mark.integration

SKILLS = "/api/v1/skills"


@pytest.fixture
def catalogue(model_demo: SimpleNamespace) -> Iterator[SimpleNamespace]:
    """The skills routes read the registry from the application, as in production."""
    missing = object()
    previous = getattr(app.state, "skill_registry", missing)
    app.state.skill_registry = model_demo.skills
    try:
        yield model_demo
    finally:
        if previous is missing:
            del app.state.skill_registry
        else:
            app.state.skill_registry = previous


def test_only_an_installed_orchestrator_skill_is_internal() -> None:
    internal = _run_orchestrator_skills()
    assert internal == {"orchestration-chat-demo"}
    # A skill that instructs a run's tasks is an ordinary skill.
    assert "contract-qa" not in internal
    # New harness pins prompt files, so it names no skill to hide or to list.
    harness = next(p for p in registered_profiles() if p.id == "new_harness_v1")
    assert (harness.root_skill, harness.child_skill) == ("", "")


async def test_the_catalogue_and_the_autocomplete_leave_it_out(catalogue: SimpleNamespace) -> None:
    api = catalogue
    for scope in ("all", "builtin"):
        response = await api.client.get(SKILLS, params={"scope": scope})
        assert response.status_code == 200, response.text
        names = {skill["name"] for skill in response.json()}
        assert "contract-qa" in names and "nda-review" in names
        assert "orchestration-chat-demo" not in names
        # Never a skill: the engine's prompt files, and the retired orchestrator skill.
        assert not {n for n in names if n.startswith("new_harness")}
        assert "contract-questions-orchestrator" not in names
    for query in ("orch", "contract", ""):
        response = await api.client.get(f"{SKILLS}/autocomplete", params={"q": query, "limit": 25})
        assert response.status_code == 200, response.text
        slugs = {row["slug"] for row in response.json()["results"]}
        assert "orchestration-chat-demo" not in slugs
    found = await api.client.get(f"{SKILLS}/autocomplete", params={"q": "contract-qa"})
    assert "contract-qa" in {row["slug"] for row in found.json()["results"]}


async def test_it_can_still_be_read_by_name(catalogue: SimpleNamespace) -> None:
    """Hidden from the picker, not from the reader: its text is open work product."""
    response = await catalogue.client.get(f"{SKILLS}/orchestration-chat-demo")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "orchestration-chat-demo"
    # A prompt file is not reachable through the skills routes under any name.
    for name in ("new_harness", "orchestrator.v1"):
        assert (await catalogue.client.get(f"{SKILLS}/{name}")).status_code == 404
