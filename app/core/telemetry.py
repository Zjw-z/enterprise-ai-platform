"""OpenTelemetry tracing adapter used by the HTTP access layer."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Span, Tracer


class PlatformTelemetry:
    """Own the SDK provider instead of mutating OpenTelemetry global state."""

    def __init__(
        self,
        *,
        service_name: str,
        enabled: bool = False,
        endpoint: str | None = None,
        sample_ratio: float = 1.0,
    ) -> None:
        self.enabled = enabled
        self.provider: TracerProvider | None = None
        self.tracer: Tracer | None = None
        if not enabled:
            return

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": service_name}
            ),
            sampler=TraceIdRatioBased(sample_ratio),
        )
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=endpoint)
                )
            )
        self.provider = provider
        self.tracer = provider.get_tracer(
            "enterprise-ai-platform.http"
        )

    def start_span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> AbstractContextManager[Span | None]:
        if self.tracer is None:
            return nullcontext(None)
        return self.tracer.start_as_current_span(
            name,
            attributes=attributes,
        )

    def shutdown(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()
