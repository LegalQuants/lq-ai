"""ADR 0038 D2: a governed run is traced across API, worker, gateway and provider.

A run's spans nest as ``orchestration.job`` (one worker invocation) >
``orchestration.run`` (one claimed session) > ``orchestration.effect`` (one
guarded step) > ``autonomous.tool_call`` (the chokepoint). Their attributes
are identifiers and labels only: never the goal, a document, a model answer
or the model's stated reason for a tool call. A refused tool call is a step
too, with nothing beneath it. A failure marks the spans it passed through
with the exception's class and never its message. The trace context rides
the queue, so the worker's spans join the trace of whatever queued the job,
and a malformed context starts a new trace instead of failing the job.

Real Postgres, guard, worker and checkpoint paths; the provider is the
controlled double of the model harness, and spans are captured in memory.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext, StatusCode
from tests.autonomous.orchestration.model_harness import (
    GOAL,
    approve,
    job,
    messages,
    new_chat,
    read,
    run_to_completion,
    start_in_chat,
    tool_call,
)

from app.main import app
from app.workers import queue
from app.workers.orchestration_worker import orchestration_session_job

pytestmark = pytest.mark.integration

# The stated reason in the harness's default child script (a read_document call).
REASON = "The agreement is needed."
AGREEMENT = (
    Path(__file__).resolve().parents[4]
    / "skills"
    / "orchestration-chat-demo"
    / "reference"
    / "fictional-agreement.md"
)
# Single-line ASCII phrases from the agreement, so that JSON escaping cannot hide them.
AGREEMENT_PHRASES = ("Term and renewal", "Paper Lantern Ltd", "USD 200 per month")
# W3C traceparent: version, trace id (32 hex), parent span id (16 hex), flags.
TRACEPARENT = re.compile(r"^00-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-[0-9a-f]{2}$")
# An identifier or a label: no spaces or punctuation that free text would need.
LABEL = re.compile(r"[A-Za-z0-9_.:\-]{0,64}")

# A well-formed traceparent that names no span of ours.
UNRELATED_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
UNRELATED = SpanContext(
    trace_id=0x4BF92F3577B34DA6A3CE929D0E0E4736, span_id=0x00F067AA0BA902B7, is_remote=True
)

# Written by a failing span, and only by a failure.
ERROR_KEY = "error.type"
JOB_KEYS = {"orchestration.root_id", "orchestration.session_id", "orchestration.outcome"}
RUN_KEYS = JOB_KEYS | {"orchestration.profile", "orchestration.role", "orchestration.stage"}
EFFECT_KEYS = {
    "orchestration.root_id",
    "orchestration.session_id",
    "orchestration.phase",
    "orchestration.intent",
    "orchestration.skill",
    "orchestration.step_kind",
}
# A span that failed never reached its outcome.
FAILED_RUN_KEYS = (RUN_KEYS - {"orchestration.outcome"}) | {ERROR_KEY}
FAILED_EFFECT_KEYS = EFFECT_KEYS | {ERROR_KEY}

# Stands in for what an error message can carry: SQL parameters, a provider's
# echo of a prompt, a validation error quoting its input.
SECRET = "SECRET-run-content-that-must-never-reach-a-span"

Queued = tuple[tuple[Any, ...], dict[str, Any]]


class SecretFailure(Exception):
    """An error whose message carries run content."""


# --- Capturing spans ----------------------------------------------------------


@pytest.fixture(scope="module")
def _module_exporter() -> InMemorySpanExporter:
    """Capture this module's spans.

    The OTel SDK allows one global provider per process, so reuse the one
    another module installed and attach to it. The app's module-level tracers
    are proxies and follow whichever provider is installed.
    """
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def span_exporter(_module_exporter: InMemorySpanExporter) -> Iterator[InMemorySpanExporter]:
    _module_exporter.clear()
    yield _module_exporter
    _module_exporter.clear()


async def test_an_sdk_provider_alone_does_not_enable_http_tracing(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Native FastAPI telemetry must not bypass the app's explicit opt-in."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert span_exporter.get_finished_spans() == ()


class RecordingPool:
    """Stands in for the arq pool: records what would be queued, queues nothing."""

    def __init__(self) -> None:
        self.calls: list[Queued] = []

    async def get(self) -> RecordingPool:
        return self

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def named(spans: Sequence[ReadableSpan], name: str) -> list[ReadableSpan]:
    """The spans with this name, in the order they started."""
    return sorted((s for s in spans if s.name == name), key=lambda s: s.start_time or 0)


def ours(spans: Sequence[ReadableSpan]) -> list[ReadableSpan]:
    """The orchestration and autonomous spans: the families these tests guard."""
    return [s for s in spans if s.name.startswith(("orchestration.", "autonomous."))]


def ancestors(span: ReadableSpan, by_id: Mapping[int, ReadableSpan]) -> Iterator[ReadableSpan]:
    """The span's parents, nearest first, as far as they were exported."""
    parent = span.parent
    while parent is not None and parent.span_id in by_id:
        span = by_id[parent.span_id]
        yield span
        parent = span.parent


def parent_of(span: ReadableSpan, by_id: Mapping[int, ReadableSpan]) -> ReadableSpan:
    assert span.parent is not None, f"{span.name} has no parent"
    assert span.parent.span_id in by_id, f"{span.name}'s parent was not exported"
    return by_id[span.parent.span_id]


def nearest(span: ReadableSpan, name: str, by_id: Mapping[int, ReadableSpan]) -> ReadableSpan:
    """The closest ancestor with this name. Other spans may sit in between."""
    found = next((a for a in ancestors(span, by_id) if a.name == name), None)
    assert found is not None, f"{span.name} is not under an {name} span"
    return found


def children_of(span: ReadableSpan, spans: Sequence[ReadableSpan]) -> list[ReadableSpan]:
    return [s for s in spans if s.parent is not None and s.parent.span_id == span.context.span_id]


def carried(carrier: Mapping[str, str]) -> tuple[int, int]:
    """The (trace id, span id) that a W3C carrier names."""
    match = TRACEPARENT.match(carrier["traceparent"])
    assert match is not None, carrier
    return int(match["trace"], 16), int(match["span"], 16)


def assert_continues(job_span: ReadableSpan, parent: SpanContext) -> None:
    """The job's span is a child of ``parent`` in the same trace, reached by carrier."""
    assert job_span.name == "orchestration.job"
    assert job_span.context.trace_id == parent.trace_id
    assert job_span.parent is not None
    assert job_span.parent.span_id == parent.span_id
    assert job_span.parent.is_remote


def last_job(exporter: InMemorySpanExporter) -> ReadableSpan:
    return named(exporter.get_finished_spans(), "orchestration.job")[-1]


def recorded_text(span: ReadableSpan) -> Iterator[str]:
    """Every string a span carries: its name, attribute values, status and event data."""
    yield span.name
    yield from (str(value) for value in attrs(span).values())
    if span.status.description:
        yield span.status.description
    for event in span.events:
        yield event.name
        yield from (str(value) for value in (event.attributes or {}).values())


def span_text(spans: Sequence[ReadableSpan]) -> str:
    """Everything the orchestration and autonomous spans carry, as one string."""
    return "\n".join(text for s in ours(spans) for text in recorded_text(s))


def assert_labels_only(spans: Sequence[ReadableSpan]) -> None:
    """Nothing these spans carry could be free text."""
    assert [
        (s.name, t) for s in ours(spans) for t in recorded_text(s) if not LABEL.fullmatch(t)
    ] == []


def assert_quiet(spans: Sequence[ReadableSpan], secret: str) -> None:
    """No exception event, none of the secret, and nothing that could be free text."""
    assert ours(spans)
    assert [s.name for s in ours(spans) if any(e.name == "exception" for e in s.events)] == []
    assert secret not in span_text(spans)
    assert_labels_only(spans)


def assert_failed_as(span: ReadableSpan, error: str) -> None:
    """The span failed with this exception class, and its record names the class and no more."""
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == error
    assert attrs(span)[ERROR_KEY] == error


def assert_unfailed(span: ReadableSpan) -> None:
    assert span.status.status_code is StatusCode.UNSET
    assert ERROR_KEY not in attrs(span)


def provider_saw(gateway: Any) -> str:
    """Everything the controlled provider was sent: messages, tool-call names and arguments."""
    seen: list[str] = []
    for request in gateway.requests:
        for message in request.messages:
            seen.append(message.content or "")
            for call in message.tool_calls or []:
                seen.extend((call["function"]["name"], call["function"]["arguments"]))
    return "\n".join(seen)


async def approved(api: SimpleNamespace) -> tuple[str, list[str]]:
    """A chat-hosted run, planned and approved, with its children waiting to run."""
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]
    assert await job(api, root) == "completed"
    planned = await read(api, root)
    await approve(api, planned)
    assert await job(api, root) == "waiting_children"
    return root, [c["dispatch_id"] for c in planned["tree"]["plan"]["children"]]


# --- 1. A run's spans -----------------------------------------------------------


async def test_a_run_leaves_nested_spans_with_identifiers_and_labels_only(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    started = await start_in_chat(api, chat_id)
    root = started["root_id"]
    final = await run_to_completion(api, started)
    children = [c["dispatch_id"] for c in final["tree"]["plan"]["children"]]
    assert len(children) == 2

    spans = span_exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    jobs = named(spans, "orchestration.job")
    runs = named(spans, "orchestration.run")
    effects = named(spans, "orchestration.effect")
    calls = named(spans, "autonomous.tool_call")

    # One job span per worker invocation: plan, root, each child, root again.
    assert len(jobs) == 3 + len(children)
    assert Counter(attrs(j)["orchestration.session_id"] for j in jobs) == Counter(
        [root, root, root, *children]
    )
    assert Counter(attrs(j)["orchestration.outcome"] for j in jobs) == Counter(
        {"completed": 2 + len(children), "waiting_children": 1}
    )

    # One run span for the planning stage, the root's execution (it waits, then
    # finishes) and each child.
    assert Counter(
        (
            attrs(r)["orchestration.role"],
            attrs(r)["orchestration.stage"],
            attrs(r)["orchestration.outcome"],
        )
        for r in runs
    ) == Counter(
        {
            ("root", "planning", "completed"): 1,
            ("root", "execution", "waiting_children"): 1,
            ("root", "execution", "completed"): 1,
            ("child", "execution", "completed"): len(children),
        }
    )
    assert {attrs(r)["orchestration.profile"] for r in runs} == {"model_demo_v1"}
    assert {
        attrs(r)["orchestration.session_id"]
        for r in runs
        if attrs(r)["orchestration.role"] == "child"
    } == set(children)

    # Effect spans cover planning, each model turn, the document read and the synthesis.
    intents = {attrs(e)["orchestration.intent"] for e in effects}
    step_kinds = {attrs(e)["orchestration.step_kind"] for e in effects}
    assert "run_skill" in intents
    assert {"planning", "model_turn", "document_read", "synthesis"} <= step_kinds
    # Each is labelled with the skill pinned for the session that took the step.
    for effect in effects:
        expected = (
            "orchestration-chat-demo"
            if attrs(effect)["orchestration.session_id"] == root
            else "contract-qa"
        )
        assert attrs(effect)["orchestration.skill"] == expected

    # Exactly the documented attributes: no key outside this allow-list.
    for family, keys in ((jobs, JOB_KEYS), (runs, RUN_KEYS), (effects, EFFECT_KEYS)):
        assert {frozenset(attrs(s)) for s in family} == {frozenset(keys)}
    assert {attrs(s)["orchestration.root_id"] for s in (*jobs, *runs, *effects)} == {root}
    # ``error.type`` is permitted on every family, but only a failure writes it.
    assert [s.name for s in ours(spans) if ERROR_KEY in attrs(s)] == []
    assert {s.status.status_code for s in ours(spans)} == {StatusCode.UNSET}

    # Nesting: job > run > effect > chokepoint call, with the same session throughout.
    for run in runs:
        job_span = parent_of(run, by_id)
        assert job_span.name == "orchestration.job"
        assert attrs(job_span)["orchestration.session_id"] == attrs(run)["orchestration.session_id"]
    for effect in effects:
        run = nearest(effect, "orchestration.run", by_id)
        assert attrs(effect)["orchestration.session_id"] == attrs(run)["orchestration.session_id"]
    for call in calls:
        effect = nearest(call, "orchestration.effect", by_id)
        assert attrs(call)["autonomous.session_id"] == attrs(effect)["orchestration.session_id"]
        assert attrs(call)["autonomous.tool"] == attrs(effect)["orchestration.intent"]
    # Every guarded step went through the chokepoint, and only those did.
    assert {nearest(c, "orchestration.effect", by_id).context.span_id for c in calls} == {
        e.context.span_id for e in effects
    }

    # Text the run really handled, so that its absence from the spans means something.
    delivered = (await messages(api, chat_id))[1]["content"]
    assert delivered == api.gateway.synthesis_answer
    handled = provider_saw(api.gateway) + "\n" + delivered
    agreement = AGREEMENT.read_text(encoding="utf-8")
    assert all(phrase in agreement for phrase in AGREEMENT_PHRASES)
    reached = {
        "the user's goal": GOAL,
        "a planned task's question": json.loads(api.gateway.proposal)["tasks"][0]["question"],
        "an agreement heading": AGREEMENT_PHRASES[0],
        "an agreement party": AGREEMENT_PHRASES[1],
        "an agreement clause": AGREEMENT_PHRASES[2],
        "the model's stated reason": REASON,
        "the start of a child's answer": api.gateway.child_answer[:50],
        "the start of the synthesis answer": api.gateway.synthesis_answer[:50],
    }
    for label, text in reached.items():
        assert text in handled, f"{label} never reached the run, so its absence proves nothing"
    forbidden = {
        **reached,
        "a child's whole answer": api.gateway.child_answer,
        "the whole synthesis answer": api.gateway.synthesis_answer,
    }

    # Identifiers and labels only: no known text appears in any orchestration or
    # autonomous span, and nothing a span carries could be free text. The count
    # makes a new span family fail here, so that its attributes get reviewed.
    assert len(ours(spans)) == len(jobs) + len(runs) + len(effects) + len(calls)
    assert [label for label, text in forbidden.items() if text in span_text(spans)] == []
    assert_labels_only(spans)


# --- 2. The trace is carried through the queue ------------------------------------


async def test_enqueuing_a_job_carries_the_active_trace_context(
    span_exporter: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = RecordingPool()
    monkeypatch.setattr(queue, "_get_m3a6_pool", pool.get)
    root_id, session_id = uuid4(), uuid4()
    tracer = trace.get_tracer("lq-ai-api-test")

    with tracer.start_as_current_span("POST /chats/{chat_id}/runs") as request:
        assert await queue.enqueue_orchestration_job(root_id, session_id) is True
    queued_by = request.get_span_context()

    ((args, kwargs),) = pool.calls
    assert args[:3] == ("orchestration_session_job", str(root_id), str(session_id))
    assert kwargs == {"_job_id": f"orchestration:{session_id}"}
    # The job's third argument is the trace context of the span that queued it.
    assert len(args) == 4 and isinstance(args[3], dict)
    assert carried(args[3]) == (queued_by.trace_id, queued_by.span_id)

    # With no active span there is nothing to carry; the job is still queued.
    pool.calls.clear()
    assert not trace.get_current_span().get_span_context().is_valid
    assert await queue.enqueue_orchestration_job(root_id, session_id) is True
    ((args, kwargs),) = pool.calls
    assert args[:3] == ("orchestration_session_job", str(root_id), str(session_id))
    assert kwargs == {"_job_id": f"orchestration:{session_id}"}
    assert isinstance(args[3], dict) and "traceparent" not in args[3]


async def test_a_job_continues_the_trace_it_was_queued_under(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]
    tracer = trace.get_tracer("lq-ai-api-test")

    carrier: dict[str, str] = {}
    with tracer.start_as_current_span("POST /chats/{chat_id}/runs") as request:
        inject(carrier)
    queued_by = request.get_span_context()

    # Run the job outside the request's span: only the carrier can link them.
    assert not trace.get_current_span().get_span_context().is_valid
    assert await orchestration_session_job(api.ctx, root, root, carrier) == {"status": "completed"}

    spans = span_exporter.get_finished_spans()
    assert_continues(last_job(span_exporter), queued_by)
    # Everything the job did, down to the guarded model call, is in that trace.
    assert {s.name for s in ours(spans)} == {
        "orchestration.job",
        "orchestration.run",
        "orchestration.effect",
        "autonomous.tool_call",
    }
    assert {s.context.trace_id for s in ours(spans)} == {queued_by.trace_id}


async def test_a_job_queued_by_an_older_build_still_runs_in_a_trace_of_its_own(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]

    # An older build queued only the two identifiers: there is no trace argument.
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "completed"}

    spans = span_exporter.get_finished_spans()
    (job_span,) = named(spans, "orchestration.job")
    assert job_span.parent is None
    assert attrs(job_span) == {
        "orchestration.root_id": root,
        "orchestration.session_id": root,
        "orchestration.outcome": "completed",
    }
    # Its work is traced beneath it as usual.
    (run,) = named(spans, "orchestration.run")
    assert run.parent is not None and run.parent.span_id == job_span.context.span_id
    assert len(api.gateway.requests) == 1


async def test_a_malformed_trace_argument_never_fails_the_job(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whoever can write to the queue can write this argument. It grants nothing.

    A job for an unknown run is the cheapest job there is; the trace argument
    is read before anything else, so the outcome is the same for any job.
    """
    api = model_demo
    forged: list[Any] = [
        None,
        {"traceparent": 5},
        {5: "x"},
        [("traceparent", UNRELATED_TRACEPARENT)],
        "traceparent",
        {"traceparent": "garbage"},
        {"traceparent": f"00-{'0' * 32}-{'0' * 16}-01"},
    ]
    for carrier in forged:
        span_exporter.clear()
        missing = str(uuid4())
        assert await orchestration_session_job(api.ctx, missing, missing, carrier) == {
            "status": "stopped"
        }
        # A fresh trace: a root span, and not the one the carrier names.
        (job_span,) = span_exporter.get_finished_spans()
        assert job_span.parent is None, carrier
        assert job_span.context.trace_id != UNRELATED.trace_id, carrier

    # A well-formed carrier is continued even though it names no span of ours,
    # and entries that are not strings are dropped from beside it.
    well_formed: list[Any] = [
        {"traceparent": UNRELATED_TRACEPARENT},
        {"traceparent": UNRELATED_TRACEPARENT, "tracestate": 5, 7: "x"},
    ]
    for carrier in well_formed:
        span_exporter.clear()
        missing = str(uuid4())
        assert await orchestration_session_job(api.ctx, missing, missing, carrier) == {
            "status": "stopped"
        }
        (job_span,) = span_exporter.get_finished_spans()
        assert_continues(job_span, UNRELATED)

    # Any error from the propagator is a missing parent, not a failed job.
    def explode(carrier: Any) -> Any:
        raise RuntimeError(SECRET)

    monkeypatch.setattr("app.workers.orchestration_worker.extract", explode)
    span_exporter.clear()
    missing = str(uuid4())
    assert await orchestration_session_job(
        api.ctx, missing, missing, {"traceparent": UNRELATED_TRACEPARENT}
    ) == {"status": "stopped"}
    (job_span,) = span_exporter.get_finished_spans()
    assert job_span.parent is None
    assert_unfailed(job_span)
    assert not api.gateway.requests


async def test_a_runs_trace_follows_it_from_each_request_and_job_to_the_next_job(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real call sites queue the next job under their own span.

    The harness records wake-ups instead of queueing them. Here the real
    ``enqueue_orchestration_job`` runs at both the API and worker call sites,
    only the arq pool is faked, and each job is run with exactly the arguments
    that were queued for it.
    """
    api = model_demo
    pool = RecordingPool()
    monkeypatch.setattr(queue, "_get_m3a6_pool", pool.get)
    for site in ("app.api.orchestration", "app.workers.orchestration_worker"):
        monkeypatch.setattr(f"{site}.enqueue_orchestration_job", queue.enqueue_orchestration_job)
    tracer = trace.get_tracer("lq-ai-api-test")

    async def run_queued(call: Queued) -> str:
        args, _ = call
        assert args[0] == "orchestration_session_job"
        return (await orchestration_session_job(api.ctx, *args[1:]))["status"]

    chat_id = await new_chat(api)
    with tracer.start_as_current_span("POST /chats/{chat_id}/runs") as start_request:
        started = await start_in_chat(api, chat_id)
    root = started["root_id"]

    # The start request queued planning under its span; the job continues it.
    (planning,) = pool.calls
    start_context = start_request.get_span_context()
    assert carried(planning[0][3]) == (start_context.trace_id, start_context.span_id)
    assert await run_queued(planning) == "completed"
    assert_continues(last_job(span_exporter), start_context)

    # Approval queued the root's execution under the approval request's span.
    planned = await read(api, root)
    children = [c["dispatch_id"] for c in planned["tree"]["plan"]["children"]]
    pool.calls.clear()
    with tracer.start_as_current_span("POST /orchestration/{root_id}/approve") as approval:
        await approve(api, planned)
    (execution,) = pool.calls
    approval_context = approval.get_span_context()
    assert carried(execution[0][3]) == (approval_context.trace_id, approval_context.span_id)
    pool.calls.clear()
    assert await run_queued(execution) == "waiting_children"
    root_job = last_job(span_exporter)
    assert_continues(root_job, approval_context)

    # The root job woke its tree from inside its own span, so each child's job
    # continues the root job, in the approval's trace.
    woken = list(pool.calls)
    assert {c[0][2] for c in woken} >= set(children)
    assert {carried(c[0][3]) for c in woken} == {
        (root_job.context.trace_id, root_job.context.span_id)
    }
    for call in (c for c in woken if c[0][2] in children):
        assert await run_queued(call) == "completed"
        child_job = last_job(span_exporter)
        assert_continues(child_job, root_job.context)
        assert attrs(child_job)["orchestration.session_id"] == call[0][2]


# --- 3. A disabled or stopped job says so without touching the provider ------------


async def test_a_disabled_job_says_so_before_it_opens_a_span_or_calls_the_provider(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]

    with monkeypatch.context() as switched:
        switched.setattr(api.runtime.settings, "orchestration_chat_enabled", False)
        assert await orchestration_session_job(api.ctx, root, root) == {"status": "disabled"}
        # With every profile off the job returns before it opens its span, so a
        # disabled worker leaves no trace.
        assert span_exporter.get_finished_spans() == ()
        assert not api.gateway.requests
        # Nothing was claimed or planned: the run is exactly as it was.
        assert (await read(api, root))["status"] == "planning"

    # The same job, with the switch back on, plans the run and is traced.
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "completed"}
    assert attrs(last_job(span_exporter))["orchestration.outcome"] == "completed"
    assert len(api.gateway.requests) == 1


async def test_a_job_for_a_profile_the_operator_switched_off_says_disabled_in_its_span(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]

    # Another profile keeps the worker enabled, so the job runs far enough to
    # find that this run's own profile is off.
    with monkeypatch.context() as switched:
        switched.setattr(api.runtime.settings, "orchestration_chat_enabled", False)
        switched.setattr(api.runtime.settings, "new_harness_enabled", True)
        assert await orchestration_session_job(api.ctx, root, root) == {"status": "disabled"}

        (job_span,) = span_exporter.get_finished_spans()
        assert job_span.name == "orchestration.job"
        assert_unfailed(job_span)
        assert attrs(job_span) == {
            "orchestration.root_id": root,
            "orchestration.session_id": root,
            "orchestration.outcome": "disabled",
        }
        assert not api.gateway.requests
        assert (await read(api, root))["status"] == "planning"


async def test_a_job_for_an_unknown_run_stops_without_calling_the_provider(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    missing = str(uuid4())

    assert await orchestration_session_job(api.ctx, missing, missing) == {"status": "stopped"}

    # The invocation is traced and says how it ended, by identifiers and one
    # label. Nothing beneath it ran.
    (job_span,) = span_exporter.get_finished_spans()
    assert job_span.name == "orchestration.job"
    assert_unfailed(job_span)
    assert attrs(job_span) == {
        "orchestration.root_id": missing,
        "orchestration.session_id": missing,
        "orchestration.outcome": "stopped",
    }
    assert not api.gateway.requests


async def test_a_job_for_a_session_outside_its_run_stops_and_says_so(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]
    stranger = str(uuid4())

    # The executor refuses with NotFound; the job catches it, so nothing failed.
    assert await orchestration_session_job(api.ctx, root, stranger) == {"status": "stopped"}

    (job_span,) = span_exporter.get_finished_spans()
    assert_unfailed(job_span)
    assert attrs(job_span) == {
        "orchestration.root_id": root,
        "orchestration.session_id": stranger,
        "orchestration.outcome": "stopped",
    }
    assert not api.gateway.requests
    assert (await read(api, root))["status"] == "planning"


async def test_a_late_duplicate_job_stops_and_runs_nothing(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    started = await start_in_chat(api, chat_id)
    root = started["root_id"]
    await run_to_completion(api, started)
    requests = len(api.gateway.requests)
    span_exporter.clear()

    # A wake-up that arrives after the run has delivered.
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "stopped"}

    spans = span_exporter.get_finished_spans()
    (job_span,) = named(spans, "orchestration.job")
    assert attrs(job_span)["orchestration.outcome"] == "stopped"
    assert not [s for s in spans if s.name in {"orchestration.effect", "autonomous.tool_call"}]
    assert len(api.gateway.requests) == requests


# --- 4. A failure leaves its class on the spans, never its message ----------------


@pytest.mark.parametrize(
    ("raised_in", "inside_the_chokepoint"),
    [
        ("app.autonomous.guard._handle_gateway_inference", True),
        ("app.autonomous.orchestration.effects.guarded_tool_call", False),
    ],
    ids=["inside-the-chokepoint-span", "outside-the-chokepoint-span"],
)
async def test_an_error_marks_the_spans_it_passed_through_by_class_and_never_by_message(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
    raised_in: str,
    inside_the_chokepoint: bool,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise SecretFailure(SECRET)

    monkeypatch.setattr(raised_in, fail)
    # The job swallows an unexpected error and says so.
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "interrupted"}

    spans = span_exporter.get_finished_spans()
    assert_quiet(spans, SECRET)
    (job_span,) = named(spans, "orchestration.job")
    (run,) = named(spans, "orchestration.run")
    (effect,) = named(spans, "orchestration.effect")
    calls = named(spans, "autonomous.tool_call")

    # Each span the error passed through names its class, and has no outcome
    # because it never finished. The attributes it did write are unchanged.
    for span in (run, effect):
        assert_failed_as(span, "SecretFailure")
    assert set(attrs(run)) == FAILED_RUN_KEYS
    assert set(attrs(effect)) == FAILED_EFFECT_KEYS
    # The chokepoint span exists only if the error was raised inside it.
    assert len(calls) == int(inside_the_chokepoint)
    for call in calls:
        assert_failed_as(call, "SecretFailure")
        assert call.parent is not None and call.parent.span_id == effect.context.span_id
    # The job caught the error: it ended normally, carrying only the outcome.
    assert_unfailed(job_span)
    assert attrs(job_span)["orchestration.outcome"] == "interrupted"
    assert set(attrs(job_span)) == JOB_KEYS


async def test_a_provider_failure_is_traced_as_the_conflict_it_becomes_not_as_the_provider_said(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = model_demo
    asked: list[int] = []

    async def fail_to_answer(request: Any, *, configuration_revision: str) -> Any:
        asked.append(1)
        raise TimeoutError(SECRET)

    monkeypatch.setattr(api.gateway, "chat_completion", fail_to_answer)
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]

    # The guard turns an unanswered, bound provider call into a Conflict with
    # a fixed message, and the job treats a Conflict as a stop.
    assert await orchestration_session_job(api.ctx, root, root) == {"status": "stopped"}
    assert asked == [1]

    spans = span_exporter.get_finished_spans()
    assert_quiet(spans, SECRET)
    (job_span,) = named(spans, "orchestration.job")
    (run,) = named(spans, "orchestration.run")
    (effect,) = named(spans, "orchestration.effect")
    (call,) = named(spans, "autonomous.tool_call")
    for span in (run, effect, call):
        assert_failed_as(span, "Conflict")
    assert_unfailed(job_span)
    assert attrs(job_span)["orchestration.outcome"] == "stopped"


async def test_an_error_in_a_childs_graph_node_leaves_each_span_its_own_class(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = model_demo
    root, children = await approved(api)

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise SecretFailure(SECRET)

    monkeypatch.setattr("app.autonomous.guard._handle_gateway_inference", fail)
    span_exporter.clear()
    assert await orchestration_session_job(api.ctx, root, children[0]) == {"status": "interrupted"}

    spans = span_exporter.get_finished_spans()
    assert_quiet(spans, SECRET)
    (job_span,) = named(spans, "orchestration.job")
    (run,) = named(spans, "orchestration.run")
    effects = named(spans, "orchestration.effect")
    calls = named(spans, "autonomous.tool_call")

    # The failing step is a model turn. Its effect and chokepoint spans carry
    # the error's own class, because the error passed through them as raised.
    (failed_effect,) = [e for e in effects if e.status.status_code is StatusCode.ERROR]
    assert attrs(failed_effect)["orchestration.step_kind"] == "model_turn"
    assert_failed_as(failed_effect, "SecretFailure")
    assert set(attrs(failed_effect)) == FAILED_EFFECT_KEYS
    (failed_call,) = [c for c in calls if c.status.status_code is StatusCode.ERROR]
    assert_failed_as(failed_call, "SecretFailure")
    assert failed_call.parent is not None
    assert failed_call.parent.span_id == failed_effect.context.span_id
    # A graph node re-raises any error as RuntimeError, without its message or
    # cause, so the run span names that class and not the original.
    assert_failed_as(run, "RuntimeError")
    assert set(attrs(run)) == FAILED_RUN_KEYS
    # The steps that finished before the failure are unmarked.
    finished = [s for s in (*effects, *calls) if s not in (failed_effect, failed_call)]
    assert finished
    for span in finished:
        assert_unfailed(span)
    assert_unfailed(job_span)
    assert attrs(job_span)["orchestration.outcome"] == "interrupted"


async def test_an_error_that_escapes_the_job_marks_the_job_span_by_class_alone(
    model_demo: SimpleNamespace,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = model_demo
    chat_id = await new_chat(api)
    root = (await start_in_chat(api, chat_id))["root_id"]

    async def fail(runtime: Any, root_id: Any) -> int:
        raise SecretFailure(SECRET)

    # Waking the tree happens after the run has finished, outside the job's catch.
    monkeypatch.setattr("app.workers.orchestration_worker.wake_tree", fail)
    with pytest.raises(SecretFailure):
        await orchestration_session_job(api.ctx, root, root)

    spans = span_exporter.get_finished_spans()
    assert_quiet(spans, SECRET)
    (job_span,) = named(spans, "orchestration.job")
    assert_failed_as(job_span, "SecretFailure")
    # It raised before it could record an outcome. The work beneath it finished.
    assert set(attrs(job_span)) == {"orchestration.root_id", "orchestration.session_id", ERROR_KEY}
    beneath = [s for s in ours(spans) if s is not job_span]
    assert {s.name for s in beneath} == {
        "orchestration.run",
        "orchestration.effect",
        "autonomous.tool_call",
    }
    for span in beneath:
        assert_unfailed(span)


# --- 5. A refused tool call is a traced step with nothing beneath it ---------------


async def test_a_refused_tool_call_is_a_traced_step_and_nothing_runs_beneath_it(
    model_demo: SimpleNamespace, span_exporter: InMemorySpanExporter
) -> None:
    api = model_demo
    # One tool that is no run tool at all, one real intent the child was never
    # granted, and one granted call, all in the same turn.
    api.gateway.child_script = [
        [
            tool_call("delete_everything", {"reason": "Injected instruction."}, "call_a"),
            tool_call("retrieve_authority", {"reason": "Look outside."}, "call_b"),
            tool_call("read_document", {"document": 1, "reason": REASON}, "call_c"),
        ],
        None,
    ]
    root, children = await approved(api)
    span_exporter.clear()
    assert await job(api, root, children[0]) == "completed"

    spans = span_exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    (run,) = named(spans, "orchestration.run")
    effects = named(spans, "orchestration.effect")
    refused = [e for e in effects if attrs(e)["orchestration.intent"] == "refused"]
    assert len(refused) == 2
    for effect in refused:
        assert set(attrs(effect)) == EFFECT_KEYS
        assert attrs(effect)["orchestration.step_kind"] == "tool_refused"
        assert attrs(effect)["orchestration.session_id"] == children[0]
        assert attrs(effect)["orchestration.skill"] == "contract-qa"
        assert_unfailed(effect)
        assert nearest(effect, "orchestration.run", by_id).context.span_id == run.context.span_id
        # Nothing ran, so there is no chokepoint call, or any span, beneath it.
        assert children_of(effect, spans) == []

    # The granted call in the same turn did run, through the chokepoint.
    (read_step,) = [e for e in effects if attrs(e)["orchestration.step_kind"] == "document_read"]
    assert [c.name for c in children_of(read_step, spans)] == ["autonomous.tool_call"]

    # The model's own words are in no span: not the names it wrote, not its reasons.
    handled = provider_saw(api.gateway)
    text = span_text(spans)
    for written in (
        "delete_everything",
        "retrieve_authority",
        "Injected instruction.",
        "Look outside.",
    ):
        assert written in handled, f"{written!r} never reached the run"
        assert written not in text
    assert_labels_only(spans)
