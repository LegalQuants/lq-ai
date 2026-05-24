# M3-F2 — Domain Spans + Rich Attributes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual OpenTelemetry domain spans (with rich, anonymization-safe attributes) to the five high-value LQ.AI operations — citation cascade, anonymization, skill dispatch, inference dispatch, and the playbook/tabular executors — so an operator in Tempo can answer "why slow / how much cost / did anonymization run / which provider+model+tier / citation outcome" one click into any chat-send trace.

**Architecture:** A new per-service `observability_helpers.py` provides a `@traced` decorator and a `record_attributes(span, **kwargs)` utility. These are explicit *domain* spans layered on top of the M1 FastAPI/httpx auto-instrumentation (they do NOT duplicate it). When OTel is disabled (the default, no `OTEL_EXPORTER_OTLP_ENDPOINT`), `trace.get_tracer()` returns a no-op tracer and span creation is effectively free — so the default production posture pays no measurable cost. Span attributes carry counts and types only, never raw entity values — the anonymization promise must not regress via the telemetry side-channel.

**Tech Stack:** Python 3.12, OpenTelemetry SDK (`opentelemetry-api/sdk` ≥1.27), `opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter` for tests, FastAPI, LangGraph (playbook/tabular executors), pytest (`asyncio_mode = auto`, `-m unit`).

---

## Decisions locked (carry into every task — "same decision in every file")

1. **Helper location:** per-service `observability_helpers.py` (`api/app/` and `gateway/app/`). The cross-service contract is the **attribute names**, not shared code (proposal §"Decisions to lock").
2. **`skill.execute` shape:** **one child span per applied skill** (a send applying 2 skills → 2 `skill.execute` spans), each carrying `skill.slug` / `skill.version` / `skill.author` (registry lookup) + `project.id` / `project.privileged` / `chat.id`. (User decision, 2026-05-23.)
3. **`inference.dispatch` location:** a **handler-level span in `gateway/app/api/inference.py`** wrapping the `gw_router.chat_completion()` call, so it carries the full join-key set including `inference.cost_usd` (read from `annotated.cost_estimate`, available in the same scope). (User decision, 2026-05-23.)
4. **`tabular.skill_id`:** **does not exist** on `TabularExecution` (verified — model has no skill_id/skill_ids column). Instrument tabular with `tabular.document_count` + `tabular.column_count` only; **file DE-314** for the missing skill linkage. Do NOT invent a skill_id.
5. **Ensemble budget-fallback event:** the cost-budget check that forces Stage-3 fallback lives in `chats.py::_resolve_ensemble_config` (runs *before* `verify()`), so the event is emitted on the **current span at that seam** (via `trace.get_current_span().add_event(...)`), not on the `citation.verify` span.
6. **Anonymization-of-attributes guarantee:** add a public `PseudonymMapper.entity_counts() -> dict[str, int]` accessor (returns a copy of `_counters`); spans read counts through it. NEVER read `_assignments` (holds raw originals) into an attribute. Enforced by `gateway/tests/test_anonymization_observability.py`.
7. **No-op safety / perf:** every span site uses the shared helper; when OTel is disabled the tracer is a no-op and `record_attributes` short-circuits on `span.is_recording() is False`. No separate `_otel_enabled()` gating at call sites. This is how "no measurable p99 regression" is satisfied — by construction, not a perf harness.
8. **Sampler / transport / OWUI:** unchanged in F2 (locked in F1's PR — `parentbased_*` via env, OTLP/HTTP, OWUI out of scope/DE-D).

## Attribute-name contract (the cross-service interface)

| Span | Attributes |
|---|---|
| `citation.verify` | `citation.method`, `citation.confidence`, `citation.partial`, `citation.tier_envelope`, `document.id` |
| `citation.stage.{exact_match,tolerant_match,paraphrase_judge,ensemble}` | `citation.stage.verified`, `citation.stage.confidence` (+ `citation.ensemble.n_judges`, `citation.ensemble.rule` on the ensemble child) |
| `anonymization.pre` / `anonymization.post` | `anonymization.enabled`, `anonymization.skip_reason` (if skipped), `anonymization.entity_count` (int), `anonymization.entity_types` (list[str]), `anonymization.tier` |
| `skill.execute` | `skill.slug`, `skill.version`, `skill.author`, `project.id`, `project.privileged`, `chat.id` |
| `inference.dispatch` | `inference.provider`, `inference.model`, `inference.tier`, `inference.outcome`, `inference.tokens_in`, `inference.tokens_out`, `inference.cost_usd` |
| `playbook.execute` | `playbook.id`, `playbook.contract_type`, `position.count`, `document.id` (+ per-position child `playbook.position.id`, `playbook.position.order`) |
| `tabular.execute` | `tabular.document_count`, `tabular.column_count` (+ per-cell child `tabular.document.id`, `tabular.column.name`) |

Span **events**: `citation.stage.exact_match` short-circuit → event `exact_match.hit`; ensemble budget fallback → event `ensemble.budget_fallback` (with `estimated_usd`, `budget_usd` attrs); anonymization skip → event per skip reason.

---

## File structure

**Create:**
- `gateway/app/observability_helpers.py` — `@traced`, `record_attributes`, `get_tracer`.
- `api/app/observability_helpers.py` — same surface, mirrored.
- `gateway/tests/test_observability_helpers.py`, `api/tests/test_observability_helpers.py`.
- `gateway/tests/test_anonymization_observability.py` — the anonymization-of-attributes guarantee.
- `api/tests/citation/test_verification_spans.py`, `api/tests/test_skill_spans.py`, `api/tests/playbooks/test_executor_spans.py`, `api/tests/tabular/test_executor_spans.py`.
- `gateway/tests/test_inference_spans.py`.

**Modify:**
- `gateway/app/anonymization/middleware.py` (pre/post spans), `gateway/app/anonymization/mapper.py` (`entity_counts()` accessor).
- `gateway/app/api/inference.py:634-695` (`inference.dispatch` span).
- `api/app/citation/verification.py` (`verify` + per-stage spans).
- `api/app/api/chats.py` (`skill.execute` per-skill spans at the dispatch seam ~1164-1177; budget-fallback event ~1473).
- `api/app/playbooks/executor.py` + `api/app/playbooks/nodes.py` (top span + per-position children).
- `api/app/tabular/executor.py` + `api/app/tabular/nodes.py` (top span + per-cell children).
- `docs/architecture.md` §OBS (domain-span inventory sentence); `docs/PRD.md` §9 (DE-314).

---

## Shared test harness (used by every span test)

Every span test uses an in-memory exporter on the global provider. Because the OTel SDK allows the global `TracerProvider` to be set once per process, use this module-scoped fixture pattern (identical to F1's `test_trace_propagation.py`):

```python
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter
```

Tests `span_exporter.clear()` at the start of each case and read `span_exporter.get_finished_spans()` after.

---

### Task 1: Gateway `observability_helpers.py`

**Files:**
- Create: `gateway/app/observability_helpers.py`
- Test: `gateway/tests/test_observability_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
# gateway/tests/test_observability_helpers.py
"""Unit tests for the gateway domain-span helpers (M3-F2)."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability_helpers import record_attributes, traced


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.mark.unit
async def test_traced_async_emits_span(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()

    @traced("thing.do")
    async def do_thing() -> int:
        return 7

    assert await do_thing() == 7
    spans = span_exporter.get_finished_spans()
    assert [s.name for s in spans] == ["thing.do"]


@pytest.mark.unit
def test_traced_sync_emits_span(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()

    @traced("thing.sync")
    def do_thing() -> int:
        return 3

    assert do_thing() == 3
    assert [s.name for s in span_exporter.get_finished_spans()] == ["thing.sync"]


@pytest.mark.unit
def test_record_attributes_drops_none_and_keeps_values(
    span_exporter: InMemorySpanExporter,
) -> None:
    span_exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("s") as span:
        record_attributes(span, foo="bar", missing=None, count=5)
    (s,) = span_exporter.get_finished_spans()
    assert s.attributes["foo"] == "bar"
    assert s.attributes["count"] == 5
    assert "missing" not in s.attributes


@pytest.mark.unit
async def test_traced_records_exception_and_reraises(
    span_exporter: InMemorySpanExporter,
) -> None:
    span_exporter.clear()

    @traced("thing.boom")
    async def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await boom()
    (s,) = span_exporter.get_finished_spans()
    assert s.status.status_code.name == "ERROR"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd gateway && ./.venv/bin/pytest tests/test_observability_helpers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability_helpers'`.

- [ ] **Step 3: Write the implementation**

```python
# gateway/app/observability_helpers.py
"""Explicit domain-span helpers for the gateway (M3-F2 / PRD §5.4).

These wrap the high-value LQ.AI operations (anonymization, inference
dispatch) in manual OpenTelemetry spans. They are deliberately separate
from the M1 FastAPI/httpx auto-instrumentation — that handles HTTP spans;
this handles *domain* spans.

No-op by default: when OTel is not initialized (no OTEL_EXPORTER_OTLP_
ENDPOINT), ``trace.get_tracer`` returns a no-op tracer whose spans never
record, so decorating a hot function costs ~a function call. ``record_
attributes`` additionally short-circuits when the span is not recording.

Attribute hygiene: callers pass counts and types, never raw entity
values — the anonymization promise must not leak via telemetry.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer
from opentelemetry.trace.status import Status, StatusCode

_F = TypeVar("_F", bound=Callable[..., Any])

_TRACER_NAME = "lq-ai-gateway"


def get_tracer(name: str = _TRACER_NAME) -> Tracer:
    """Return a tracer. No-op when OTel is not initialized."""

    return trace.get_tracer(name)


def record_attributes(span: Span, /, **attributes: Any) -> None:
    """Set non-None attributes on ``span``; skip when not recording.

    None values are dropped (OTel rejects None attribute values).
    """

    if not span.is_recording():
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def traced(span_name: str, *, tracer_name: str = _TRACER_NAME) -> Callable[[_F], _F]:
    """Decorator that wraps a sync or async callable in a domain span.

    Records exceptions and sets ERROR status before re-raising. Use the
    ``with get_tracer().start_as_current_span(...)`` form directly when a
    span must wrap only part of a function or set attributes computed
    mid-body.
    """

    def decorator(func: _F) -> _F:
        tracer = trace.get_tracer(tracer_name)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        raise

            return cast("_F", async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        return cast("_F", sync_wrapper)

    return decorator
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd gateway && ./.venv/bin/pytest tests/test_observability_helpers.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
cd gateway && ./.venv/bin/ruff format app/observability_helpers.py tests/test_observability_helpers.py && ./.venv/bin/ruff check app/observability_helpers.py tests/test_observability_helpers.py && ./.venv/bin/mypy app
cd .. && git add gateway/app/observability_helpers.py gateway/tests/test_observability_helpers.py && git commit -s -m "feat(m3-f2): gateway domain-span helpers (@traced + record_attributes)"
```

---

### Task 2: API `observability_helpers.py`

**Files:**
- Create: `api/app/observability_helpers.py` (identical surface to Task 1; change `_TRACER_NAME = "lq-ai-api"`)
- Test: `api/tests/test_observability_helpers.py` (copy Task 1's test, `from app.observability_helpers import ...`)

- [ ] **Step 1:** Copy the Task 1 test file to `api/tests/test_observability_helpers.py` verbatim (imports already use `app.observability_helpers`).
- [ ] **Step 2:** Run `cd api && ./.venv/bin/pytest tests/test_observability_helpers.py -q` → FAIL (module missing).
- [ ] **Step 3:** Copy Task 1's `observability_helpers.py` to `api/app/`, change `_TRACER_NAME = "lq-ai-api"` and the module docstring "gateway"→"api".
- [ ] **Step 4:** Run → PASS (4 passed).
- [ ] **Step 5:** `cd api && ./.venv/bin/ruff format ... && ./.venv/bin/ruff check ... && ./.venv/bin/mypy app`; commit `feat(m3-f2): api domain-span helpers (mirror of gateway)`.

---

### Task 3: Anonymization spans + counts accessor + the guarantee test

**Files:**
- Modify: `gateway/app/anonymization/mapper.py` (add `entity_counts()`), `gateway/app/anonymization/middleware.py:61-114` (pre span), and the post seam.
- Test: `gateway/tests/test_anonymization_observability.py`

- [ ] **Step 1: Write the failing guarantee test**

```python
# gateway/tests/test_anonymization_observability.py
"""Anonymization-of-attributes guarantee (M3-F2).

Span attributes for anonymization must carry COUNTS and TYPES only —
never raw entity values. If a future change leaks a PERSON name or a
MATTER_NUMBER into a span attribute, this test fails.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.anonymization.anonymizer import Anonymizer  # adjust import to the real path
from app.anonymization.middleware import pre_anonymize_request
# build a ChatCompletionRequest + AnonymizationConfig fixture mirroring
# existing tests in gateway/tests/ (reuse the anonymization test helpers).


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.mark.unit
def test_entity_count_attribute_is_int_never_names(span_exporter, ...) -> None:
    span_exporter.clear()
    # Build a request containing a known PERSON name (e.g., "Jane Doe") and a
    # MATTER_NUMBER, at a tier where anonymization applies, anonymize=True.
    pre_anonymize_request(chat_request=req, config=cfg, routed_tier=3, anonymizer=anon)
    spans = [s for s in span_exporter.get_finished_spans() if s.name == "anonymization.pre"]
    assert spans, "expected an anonymization.pre span"
    attrs = spans[0].attributes
    assert isinstance(attrs["anonymization.entity_count"], int)
    # No raw value anywhere in the attribute values.
    flat = " ".join(str(v) for v in attrs.values())
    assert "Jane Doe" not in flat
    assert "MATTER" not in flat or "matter_number_value" not in flat.lower()


@pytest.mark.unit
def test_skip_reason_recorded_when_privileged(span_exporter, ...) -> None:
    span_exporter.clear()
    # privileged request -> skipped, no entity processing
    pre_anonymize_request(chat_request=priv_req, config=cfg, routed_tier=3, anonymizer=anon)
    (s,) = [s for s in span_exporter.get_finished_spans() if s.name == "anonymization.pre"]
    assert s.attributes["anonymization.skip_reason"] == "privileged"
    assert s.attributes["anonymization.entity_count"] == 0
```

> **Executor note:** reuse the existing anonymization request/config fixtures already present in `gateway/tests/` (grep for `pre_anonymize_request(` in the test suite). Fill the `...` with those. Confirm the real entity-type names Pii detector emits (`PERSON`, `MATTER_NUMBER`, etc.) and assert on a value you injected.

- [ ] **Step 2: Run → FAIL** (no `anonymization.pre` span yet).

- [ ] **Step 3a: Add the counts accessor** to `gateway/app/anonymization/mapper.py` (class `PseudonymMapper`, near line 90):

```python
    def entity_counts(self) -> dict[str, int]:
        """Return a copy of per-entity-type replacement counts.

        Counts + type names only — never the original entity text (which
        lives in ``self._assignments`` keys and must never be exported).
        """

        return dict(self._counters)
```

- [ ] **Step 3b: Wrap pre/post in spans.** In `middleware.py`, import `from app.observability_helpers import get_tracer, record_attributes` and the skip-reason logic. Restructure `pre_anonymize_request` (lines 61-114) so the whole body runs inside one span:

```python
    tracer = get_tracer()
    with tracer.start_as_current_span("anonymization.pre") as span:
        record_attributes(span, **{"anonymization.enabled": config.enabled,
                                   "anonymization.tier": routed_tier})
        skip_reason = None
        if not config.enabled:
            skip_reason = "disabled"
        elif routed_tier not in config.apply_at_tiers:
            skip_reason = "tier_floor"
        elif chat_request.lq_ai_privileged:
            skip_reason = "privileged"
        elif not chat_request.anonymize:
            skip_reason = "request_opt_out"
        if skip_reason is not None:
            record_attributes(span, **{"anonymization.skip_reason": skip_reason,
                                       "anonymization.entity_count": 0})
            span.add_event(f"anonymization.skip.{skip_reason}")
            return None
        mapper = PseudonymMapper()
        # ... existing per-message pseudonymization loop unchanged ...
        counts = mapper.entity_counts()
        record_attributes(
            span,
            **{"anonymization.entity_count": sum(counts.values()),
               "anonymization.entity_types": sorted(counts.keys())},
        )
        return mapper
```

> Preserve the existing per-message skip (`lq_ai_skip_anonymization`) and skill-input pseudonymization exactly. The span wraps the existing logic; do not change behavior.

- [ ] **Step 3c: Post span.** Wrap `post_anonymize_response` (lines 200-223) in an `anonymization.post` span via the `@traced("anonymization.post")` decorator (it has no skip branches — decorator is enough). For the streaming path, decorate `StreamingRehydrator.process`/`flush` only if cheap; otherwise file as a sub-DE (per-chunk spans can be high-volume — prefer a single span around the rehydrator lifecycle in the streaming handler). **Default: skip per-chunk spans in F2, note DE-315 (streaming rehydration spans).**

- [ ] **Step 4: Run → PASS.** Also run the existing anonymization suite to confirm no behavior change: `./.venv/bin/pytest tests/ -k anonym -q`.

- [ ] **Step 5: Lint + mypy + commit** `feat(m3-f2): anonymization.pre/.post spans (counts+types only, no raw values)`.

---

### Task 4: `inference.dispatch` span (gateway handler)

**Files:**
- Modify: `gateway/app/api/inference.py:634-695` (non-streaming `chat_completions`).
- Test: `gateway/tests/test_inference_spans.py`

- [ ] **Step 1: Write the failing test** — use the existing inference handler test harness (grep `chat_completions` in `gateway/tests/` for the app/client fixture + a stub adapter). Drive a successful chat-completion through the TestClient with the in-memory exporter installed, then assert:

```python
@pytest.mark.unit
async def test_inference_dispatch_span_carries_join_keys(span_exporter, client, ...) -> None:
    span_exporter.clear()
    resp = await client.post("/v1/chat/completions", json=valid_body, headers=auth)
    assert resp.status_code == 200
    (s,) = [s for s in span_exporter.get_finished_spans() if s.name == "inference.dispatch"]
    assert s.attributes["inference.outcome"] == "success"
    assert s.attributes["inference.provider"]  # provider name present
    assert isinstance(s.attributes["inference.tier"], int)
    assert "inference.tokens_in" in s.attributes
    assert "inference.cost_usd" in s.attributes
```

- [ ] **Step 2: Run → FAIL** (no `inference.dispatch` span).

- [ ] **Step 3: Wrap the dispatch block.** In `chat_completions` (line ~634), open the span around the try/except + annotation:

```python
    tracer = get_tracer()
    with tracer.start_as_current_span("inference.dispatch") as span:
        try:
            result = await gw_router.chat_completion(chat_request)
        except RoutedProviderError as wrapped:
            record_attributes(span, **{
                "inference.provider": wrapped.target.provider.name,
                "inference.model": wrapped.target.native_model,
                "inference.tier": wrapped.target.routed_inference_tier,
                "inference.outcome": _outcome_label_from_error(wrapped.error)})
            await _write_failure(...)            # unchanged
            return _map_provider_error_to_response(wrapped.error)
        except NoAdapterAvailableError as exc:
            record_attributes(span, **{"inference.outcome": "unavailable",
                                       "inference.provider": candidates[0].provider.name})
            await _write_unavailable(...)        # unchanged
            return _gateway_error(...)
        # success path (unchanged), then:
        annotated = _annotate_response(result.response, target=result.target, config=config)
        usage = result.response.usage
        record_attributes(span, **{
            "inference.provider": result.target.provider.name,
            "inference.model": result.target.native_model,
            "inference.tier": result.target.routed_inference_tier,
            "inference.outcome": "success",
            "inference.tokens_in": getattr(usage, "prompt_tokens", None),
            "inference.tokens_out": getattr(usage, "completion_tokens", None),
            "inference.cost_usd": _cost_usd_float(annotated.cost_estimate)})
        # ... existing _write_success + JSONResponse return, now inside the with-block ...
```

> Add a tiny `_cost_usd_float(cost_estimate) -> float | None` helper near the top of the module that extracts the USD float from whatever shape `cost_estimate` is (inspect `_annotate_response`/`CostEstimate` for the field; likely `.usd` or `.total_usd`). Import `_outcome_label_from_error` from `app.router` (already module-level there).

- [ ] **Step 4: Run → PASS.** Run the full inference handler suite: `./.venv/bin/pytest tests/ -k "inference or chat_completion" -q` — confirm no regression.

- [ ] **Step 5: Lint + mypy --strict + commit** `feat(m3-f2): inference.dispatch span with provider/model/tier/tokens/cost/outcome`.

---

### Task 5: Citation cascade spans (`citation.verify` + per-stage)

**Files:**
- Modify: `api/app/citation/verification.py` (`verify` 523-587; stages 151-179, 182-226, 264-326, 429-517).
- Modify: `api/app/api/chats.py:~1473` (ensemble budget-fallback event).
- Test: `api/tests/citation/test_verification_spans.py`

- [ ] **Step 1: Write failing tests** (use existing `verify`/stage fixtures — grep `verify_exact_match(` and `await verify(` in `api/tests/citation/`):

```python
@pytest.mark.unit
async def test_exact_match_hit_emits_short_circuit_event(span_exporter, ...) -> None:
    span_exporter.clear()
    result = await verify(exact_candidate, document)  # text is a verbatim substring
    top = [s for s in span_exporter.get_finished_spans() if s.name == "citation.verify"][0]
    assert top.attributes["citation.method"] == "exact_match"
    assert top.attributes["citation.confidence"] == 1.0
    assert any(e.name == "exact_match.hit" for e in top.events)
    stage_names = {s.name for s in span_exporter.get_finished_spans()}
    assert "citation.stage.exact_match" in stage_names
    assert "citation.stage.tolerant_match" not in stage_names  # short-circuited

@pytest.mark.unit
async def test_ensemble_records_n_judges_and_rule(span_exporter, ...) -> None:
    ...  # drive verify() with an ensemble_config + stub gateway; assert child span attrs
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Instrument.** In `verify()`, open `citation.verify` span; set `document.id`. Wrap each stage call in a `citation.stage.<name>` child span (set `citation.stage.verified` + `citation.stage.confidence`). On the exact/tolerant short-circuit (`if result.verified: return result`), set the top-span attributes (`citation.method`, `citation.confidence`, `citation.partial`, `citation.tier_envelope`) and `span.add_event("exact_match.hit")` / `"tolerant_match.hit"` before returning. Decorate the leaf stage functions with `@traced("citation.stage.exact_match")` etc. for the child spans (sync stages decorate fine). On the final return (paraphrase/ensemble/miss), set the top-span result attributes.

- [ ] **Step 3b: Budget-fallback event** — in `chats.py::_resolve_ensemble_config` at the fallback branch (~line 1473), add:

```python
            from opentelemetry import trace
            trace.get_current_span().add_event(
                "ensemble.budget_fallback",
                attributes={"estimated_usd": float(estimated_usd),
                            "budget_usd": float(config.max_cost_per_message_usd)})
```

- [ ] **Step 4: Run → PASS.** Run `./.venv/bin/pytest tests/citation -q` — no regression.
- [ ] **Step 5: Lint + mypy + commit** `feat(m3-f2): citation.verify + per-stage spans, short-circuit + budget-fallback events`.

---

### Task 6: `skill.execute` per-skill child spans

**Files:**
- Modify: `api/app/api/chats.py` at the gateway-dispatch seam (~1164-1177, where `gw_request` is built and `effective_skills`/project flags are in scope).
- Test: `api/tests/test_skill_spans.py`

- [ ] **Step 1: Write failing test** — drive the non-streaming send path with 2 applied skills (reuse the existing send_message integration/unit harness; if too heavy, extract the span-emitting block into a small helper `_emit_skill_spans(skills, *, registry, project, chat_id)` and unit-test that helper directly). Assert two `skill.execute` spans with distinct `skill.slug`, each carrying `skill.version`, `project.id`, `project.privileged`, `chat.id`.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** a helper near the dispatch seam:

```python
def _emit_skill_spans(
    skill_slugs: list[str], *, registry: SkillRegistry | None,
    project_id: uuid.UUID, project_privileged: bool, chat_id: uuid.UUID,
) -> None:
    tracer = get_tracer()
    for slug in skill_slugs:
        skill = registry.get_skill(slug) if registry is not None else None
        with tracer.start_as_current_span("skill.execute") as span:
            record_attributes(span, **{
                "skill.slug": slug,
                "skill.version": getattr(skill, "version", None),
                "skill.author": getattr(skill, "author", None),
                "project.id": str(project_id),
                "project.privileged": project_privileged,
                "chat.id": str(chat_id)})
```

Call it just before/after building `gw_request` with `effective_skills`. (These are short-lived marker spans recording *which* skills were applied to the send — the actual prompt assembly + inference happen in the gateway under the same trace.)

- [ ] **Step 4: Run → PASS.** Run `./.venv/bin/pytest tests/ -k "send_message or chats" -q -m unit` — no regression.
- [ ] **Step 5: Lint + mypy + commit** `feat(m3-f2): skill.execute span per applied skill at the dispatch seam`.

---

### Task 7: `playbook.execute` + per-position child spans

**Files:**
- Modify: `api/app/playbooks/executor.py:67-147` (top span), `api/app/playbooks/nodes.py` (per-position children in `classify_node` ~284, `redline_node` ~418).
- Test: `api/tests/playbooks/test_executor_spans.py`

> **Context propagation (verified):** LangGraph async nodes run in the same event-loop context, and sync nodes run via `copy_context().run(...)` — so child spans created inside nodes nest under the top span automatically. No explicit context passing needed.

- [ ] **Step 1: Write failing test** — reuse the existing `run_playbook_execution` test harness (grep `run_playbook_execution(` in `api/tests/playbooks/`; it stubs the gateway). Assert one `playbook.execute` span with `playbook.id` / `playbook.contract_type` / `position.count` / `document.id`, and ≥1 `playbook.position` child span.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Instrument.** In `run_playbook_execution` (after `playbook` is loaded ~line 98, before `await graph.ainvoke(...)` line 128), wrap the ainvoke in:

```python
    tracer = get_tracer()
    with tracer.start_as_current_span("playbook.execute") as span:
        record_attributes(span, **{
            "playbook.id": str(playbook.id),
            "playbook.contract_type": playbook.contract_type,
            "position.count": len(playbook.positions),
            "document.id": str(document.id)})
        final_state = await graph.ainvoke(initial_state)
```

In `nodes.py`, inside the per-position loop of `classify_node` (and `redline_node`), wrap each iteration:

```python
        tracer = get_tracer()
        for pos in state.get("positions", []):
            with tracer.start_as_current_span("playbook.position") as span:
                record_attributes(span, **{"playbook.position.id": str(pos["id"]),
                                           "playbook.position.order": pos.get("position_order")})
                ...  # existing per-position body unchanged
```

- [ ] **Step 4: Run → PASS.** `./.venv/bin/pytest tests/playbooks -q -m unit` — no regression.
- [ ] **Step 5: Lint + mypy + commit** `feat(m3-f2): playbook.execute span + per-position children`.

---

### Task 8: `tabular.execute` + per-cell child spans + DE-314

**Files:**
- Modify: `api/app/tabular/executor.py:63-139` (top span), `api/app/tabular/nodes.py` (per-cell children in `extract_cells_node` ~190-208).
- Modify: `docs/PRD.md` §9 (DE-314).
- Test: `api/tests/tabular/test_executor_spans.py`

- [ ] **Step 1: Write failing test** — reuse the `run_tabular_execution` harness (grep in `api/tests/tabular/`). Assert one `tabular.execute` span with `tabular.document_count` + `tabular.column_count`, and ≥1 `tabular.cell` child span carrying `tabular.document.id` + `tabular.column.name`.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Instrument.** In `run_tabular_execution`, wrap `await graph.ainvoke(...)` (line 123) in a `tabular.execute` span. `document_count` is not known until `load_documents_node` runs, but `len(execution.document_ids)` IS available at the top (line 105) and `len(execution.columns)` at line 106 — use those:

```python
    tracer = get_tracer()
    with tracer.start_as_current_span("tabular.execute") as span:
        record_attributes(span, **{
            "tabular.document_count": len(execution.document_ids),
            "tabular.column_count": len(execution.columns)})
        final_state = await graph.ainvoke(initial_state)
```

In `extract_cells_node`, wrap each `(document, column)` iteration in a `tabular.cell` span with `tabular.document.id` (str) + `tabular.column.name`.

- [ ] **Step 3b: File DE-314** in `docs/PRD.md` §9: "DE-314 — Tabular executions have no skill linkage (`TabularExecution` lacks a skill_id/skill_ids column), so the `tabular.skill_id` span attribute proposed in the OTel-deepening plan cannot be emitted. Add a skill association to tabular executions (or document that columns, not executions, carry the skill reference) and emit `tabular.skill_id`."

- [ ] **Step 4: Run → PASS.** `./.venv/bin/pytest tests/tabular -q -m unit` — no regression.
- [ ] **Step 5: Lint + mypy + commit** `feat(m3-f2): tabular.execute span + per-cell children; DE-314 for missing skill linkage`.

---

### Task 9: Docs + full-suite verification

**Files:**
- Modify: `docs/architecture.md` §OBS (the "What the diagram doesn't show" observability bullet, extended in F1).

- [ ] **Step 1:** Extend the §OBS bullet with one sentence listing the F2 domain spans: "Beyond HTTP auto-instrumentation, the services emit domain spans — `citation.verify` (+ per-stage children), `anonymization.pre/.post`, `skill.execute`, `inference.dispatch` (provider/model/tier/tokens/cost/outcome), and `playbook.execute`/`tabular.execute` with per-position/per-cell children — carrying counts and types only, never raw entity values."
- [ ] **Step 2: Full unit suites green, both services:**

```bash
cd gateway && ./.venv/bin/ruff format --check app tests && ./.venv/bin/ruff check app tests && ./.venv/bin/mypy app && ./.venv/bin/pytest -m unit -q
cd ../api && ./.venv/bin/ruff format --check app tests && ./.venv/bin/ruff check app tests && ./.venv/bin/mypy app && ./.venv/bin/pytest -m unit -q
```
Expected: all green; the F1 `test_observability.py` + `test_trace_propagation.py` still pass.

- [ ] **Step 3: Rebuild backend images** so the live stack reflects F2 (no api/gateway bind-mount):

```bash
cd ~/Code/lq-ai && docker compose --profile slack --profile teams up -d --build api gateway arq-worker ingest-worker
```

- [ ] **Step 4: Commit docs** `docs(m3-f2): architecture §OBS domain-span inventory`.

---

## Self-review

**Spec coverage (proposal PR-2):**
- Citation cascade span + per-stage + short-circuit event + budget-fallback event → Task 5. ✓
- Anonymization pre/post spans + skip events + counts-only guarantee → Task 3. ✓ (streaming per-chunk spans deferred → DE-315, noted.)
- Skill runner `skill.execute` → Task 6 (per-skill, locked decision). ✓
- Inference dispatch attributes → Task 4 (handler-level, locked decision). ✓
- Playbook + tabular executors → Tasks 7, 8. ✓ (`tabular.skill_id` → DE-314, unreachable.)
- New `observability_helpers.py` per service with `@traced` + `record_attributes` → Tasks 1, 2. ✓ (does not duplicate FastAPI HTTP automation.)
- In-memory exporter tests per touched module → every task. ✓
- Anonymization-of-attributes regression test (`entity_count` int, never names) → Task 3. ✓
- No measurable p99 regression → satisfied by no-op-by-default design (Decision 7); no perf harness built. ✓

**Placeholder scan:** Task 3/4/5/6 tests contain `...` where they must reuse existing fixtures — these are flagged with explicit executor notes pointing at the grep target, not silent gaps. Acceptable because the fixtures already exist and copying them inline would duplicate large harnesses; the executor must wire them.

**Type consistency:** helper surface (`traced(span_name, *, tracer_name)`, `record_attributes(span, /, **attributes)`, `get_tracer(name)`) is identical across Tasks 1-2 and used consistently in Tasks 3-8. Span/attribute names match the contract table.

**New DEs filed by this plan:** DE-314 (tabular skill linkage), DE-315 (streaming-rehydration per-chunk spans).
