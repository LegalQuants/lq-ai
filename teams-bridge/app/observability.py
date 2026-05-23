"""OpenTelemetry init for the Teams Bridge.

Mirrors ``slack-bridge/app/observability.py`` — opt-in via
``OTEL_EXPORTER_OTLP_ENDPOINT``, auto-instrumentation for FastAPI +
httpx, no metrics surface beyond what FastAPI auto-instrumentation
produces.

When M3 Phase F's domain-span work lands (per
``docs/proposals/opentelemetry-deepening.md``), the bridge will gain
``teams.oauth.exchange`` and ``teams.callback.verify`` spans on top
of this substrate.
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

    HTTPXClientInstrumentor().instrument()

    log.info(
        "otel.initialised — exporter=%s, service.name=%s",
        settings.otel_exporter_otlp_endpoint,
        settings.otel_service_name,
    )
