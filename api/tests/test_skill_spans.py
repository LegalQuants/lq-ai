"""Unit tests for the _emit_skill_spans helper (M3-F2 / Task 6).

Tests the helper directly — the full send path is heavy to spin up,
but the helper is pure and importable without any infrastructure.
"""

from __future__ import annotations

import uuid

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.api.chats import _emit_skill_spans

# ---------------------------------------------------------------------------
# Shared OTel fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


# ---------------------------------------------------------------------------
# Fake registry helpers
# ---------------------------------------------------------------------------


class _FakeSkill:
    """Minimal skill-like object for testing span attributes."""

    def __init__(self, *, version: str, author: str | None = None) -> None:
        self.version = version
        self.author = author


class _FakeRegistry:
    """Fake SkillRegistry for unit tests — returns configured stubs."""

    def __init__(self, skills: dict[str, _FakeSkill | None]) -> None:
        self._skills = skills

    def get_skill(self, name: str) -> _FakeSkill | None:
        return self._skills.get(name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_emits_one_span_per_skill(span_exporter: InMemorySpanExporter) -> None:
    """A 2-slug send emits exactly 2 `skill.execute` spans."""
    span_exporter.clear()

    project_id = uuid.uuid4()
    chat_id = uuid.uuid4()

    registry = _FakeRegistry(
        {
            "nda-review": _FakeSkill(version="1.0.0", author="Jane"),
            "msa-review-saas": _FakeSkill(version="2.0.0", author="Bob"),
        }
    )

    _emit_skill_spans(
        ["nda-review", "msa-review-saas"],
        registry=registry,  # type: ignore[arg-type]
        project_id=project_id,
        project_privileged=False,
        chat_id=chat_id,
    )

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 2
    assert all(s.name == "skill.execute" for s in spans)

    slugs = {s.attributes["skill.slug"] for s in spans}
    assert slugs == {"nda-review", "msa-review-saas"}

    for span in spans:
        assert span.attributes["project.id"] == str(project_id)
        assert span.attributes["project.privileged"] is False
        assert span.attributes["chat.id"] == str(chat_id)


@pytest.mark.unit
def test_span_carries_version_and_author_from_registry(
    span_exporter: InMemorySpanExporter,
) -> None:
    """When the registry returns a skill with version/author, the span carries them."""
    span_exporter.clear()

    project_id = uuid.uuid4()
    chat_id = uuid.uuid4()

    registry = _FakeRegistry({"my-skill": _FakeSkill(version="1.2.0", author="Jane")})

    _emit_skill_spans(
        ["my-skill"],
        registry=registry,  # type: ignore[arg-type]
        project_id=project_id,
        project_privileged=True,
        chat_id=chat_id,
    )

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["skill.slug"] == "my-skill"
    assert span.attributes["skill.version"] == "1.2.0"
    assert span.attributes["skill.author"] == "Jane"
    assert span.attributes["project.privileged"] is True


@pytest.mark.unit
def test_unknown_skill_omits_version_author(
    span_exporter: InMemorySpanExporter,
) -> None:
    """When the registry returns None for the slug, skill.version/author are absent."""
    span_exporter.clear()

    project_id = uuid.uuid4()
    chat_id = uuid.uuid4()

    # Registry has nothing for "unknown-skill"
    registry = _FakeRegistry({})

    _emit_skill_spans(
        ["unknown-skill"],
        registry=registry,  # type: ignore[arg-type]
        project_id=project_id,
        project_privileged=False,
        chat_id=chat_id,
    )

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["skill.slug"] == "unknown-skill"
    # version and author should NOT be in attributes (None → dropped by record_attributes)
    assert "skill.version" not in span.attributes
    assert "skill.author" not in span.attributes


@pytest.mark.unit
def test_empty_slug_list_emits_no_spans(span_exporter: InMemorySpanExporter) -> None:
    """An empty skills list emits no spans at all."""
    span_exporter.clear()

    _emit_skill_spans(
        [],
        registry=None,
        project_id=uuid.uuid4(),
        project_privileged=False,
        chat_id=uuid.uuid4(),
    )

    assert len(span_exporter.get_finished_spans()) == 0


@pytest.mark.unit
def test_none_registry_emits_span_without_version_author(
    span_exporter: InMemorySpanExporter,
) -> None:
    """When registry=None, skill.slug/project/chat attributes are still present."""
    span_exporter.clear()

    project_id = uuid.uuid4()
    chat_id = uuid.uuid4()

    _emit_skill_spans(
        ["nda-review"],
        registry=None,
        project_id=project_id,
        project_privileged=True,
        chat_id=chat_id,
    )

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["skill.slug"] == "nda-review"
    assert "skill.version" not in span.attributes
    assert "skill.author" not in span.attributes
    assert span.attributes["project.id"] == str(project_id)
    assert span.attributes["chat.id"] == str(chat_id)


@pytest.mark.unit
def test_none_project_id_omits_project_id_attribute(
    span_exporter: InMemorySpanExporter,
) -> None:
    """project_id=None → project.id is absent (not the literal string 'None')."""
    span_exporter.clear()
    _emit_skill_spans(
        ["nda-review"],
        registry=None,
        project_id=None,
        project_privileged=False,
        chat_id=uuid.uuid4(),
    )
    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert "project.id" not in spans[0].attributes
