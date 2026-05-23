"""OpenTelemetry init for the Slack Bridge.

Mirrors ``api/app/observability.py`` and ``gateway/app/observability.py``
at the M1 substrate level: opt-in via ``OTEL_EXPORTER_OTLP_ENDPOINT``,
auto-instrumentation for FastAPI + httpx, no metrics surface beyond
what FastAPI auto-instrumentation produces (the bridge has no
domain-specific Prometheus metrics today).

When M3 Phase F's domain-span work (per
``docs/proposals/opentelemetry-deepening.md``) lands, the bridge will
gain explicit ``slack.oauth.exchange`` and ``slack.callback.verify``
spans. The substrate here makes those additive.
"""

from __future__ import annotations

import logging

from .config import Settings

log = logging.getLogger(__name__)


def init_otel(settings: Settings) -> None:
    """Initialise OTel TracerProvider + auto-instrumentations.

    No-op when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset (PRD §5.7
    no-telemetry-by-default promise applies here too).
    """

    if not settings.otel_exporter_otlp_endpoint:
        log.info(
            "otel.disabled — OTEL_EXPORTER_OTLP_ENDPOINT unset; bridge will "
            "emit no telemetry. Per PRD §5.7's no-telemetry-by-default."
        )
        return

    # Lazy import keeps the OTel surface out of the startup hot-path
    # for operators who don't opt in.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": settings.otel_service_name, "service.namespace": "lq-ai"}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    # FastAPIInstrumentor is wired in main.py via `app.add_middleware(...)`
    # equivalent — instrumentor pattern handles that. httpx instrumentation
    # is process-global and only needs to be enabled once here.
    HTTPXClientInstrumentor().instrument()

    log.info(
        "otel.initialised — exporter=%s, service.name=%s",
        settings.otel_exporter_otlp_endpoint,
        settings.otel_service_name,
    )
