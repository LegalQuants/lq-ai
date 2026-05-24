"""Explicit domain-span helpers for the api (M3-F2 / PRD §5.4).

These wrap the high-value LQ.AI operations (citation cascade, skill
dispatch, playbook + tabular executors) in manual OpenTelemetry spans.
They are deliberately separate from the M1 FastAPI/httpx
auto-instrumentation — that handles HTTP spans; this handles *domain*
spans.

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
from collections.abc import Callable
from typing import Any, TypeVar, cast

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer
from opentelemetry.trace.status import Status, StatusCode

_F = TypeVar("_F", bound=Callable[..., Any])

_TRACER_NAME = "lq-ai-api"


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
                # Disable the SDK's automatic exception recording so the
                # decorator is the sole author of the exception event +
                # ERROR status (otherwise the span carries a duplicate
                # exception event).
                with tracer.start_as_current_span(
                    span_name,
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        raise

            return cast("_F", async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(
                span_name,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        return cast("_F", sync_wrapper)

    return decorator
