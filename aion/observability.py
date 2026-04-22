"""OpenTelemetry setup para AION.

Instrumenta automaticamente:
  - FastAPI (requests, spans por endpoint)
  - httpx (outbound calls ao LLM provider)
  - Manual spans em pontos críticos (ESTIXE classify, output guard)

Desativa silenciosamente se OTEL_EXPORTER_OTLP_ENDPOINT não estiver setado.

Uso:
    from aion.observability import setup_telemetry
    setup_telemetry(app)  # chamar uma vez no lifespan do FastAPI
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("aion.observability")

_tracer = None


def setup_telemetry(app) -> None:
    """Setup OpenTelemetry tracing. No-op se OTEL_EXPORTER_OTLP_ENDPOINT não setado."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        logger.info("OpenTelemetry disabled (no OTEL_EXPORTER_OTLP_ENDPOINT)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError as e:
        logger.warning("OpenTelemetry libs not available: %s", e)
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", "aion")
    replica_id = os.environ.get("AION_REPLICA_ID", "local")

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: os.environ.get("AION_VERSION", "0.1.0"),
        "service.instance.id": replica_id,
        "deployment.environment": os.environ.get("AION_ENVIRONMENT", "dev"),
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI + httpx
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready,/metrics")
    HTTPXClientInstrumentor().instrument()

    global _tracer
    _tracer = trace.get_tracer(service_name)
    logger.info("OpenTelemetry enabled: service=%s replica=%s endpoint=%s",
                service_name, replica_id, endpoint)


def get_tracer():
    """Get the global tracer. Returns None if OTel not initialized."""
    return _tracer


def traced_span(name: str, **attributes):
    """Decorator/context manager para span custom.

    Uso:
        with traced_span("estixe.classify", tenant="nubank") as span:
            ...
            span.set_attribute("risk.category", "fraud_enablement")
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        if _tracer is None:
            yield _DummySpan()
            return
        with _tracer.start_as_current_span(name) as span:
            for k, v in attributes.items():
                span.set_attribute(k, v)
            yield span

    return _ctx()


class _DummySpan:
    """No-op span quando OTel não está ativo (evita crashes)."""
    def set_attribute(self, *a, **kw): pass
    def add_event(self, *a, **kw): pass
    def record_exception(self, *a, **kw): pass
    def set_status(self, *a, **kw): pass
