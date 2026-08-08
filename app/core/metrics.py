"""Prometheus metrics with bounded, low-cardinality labels."""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.protocol.event import Event


class PlatformMetrics:
    """Own an isolated registry so tests and multiple app instances are safe."""

    CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

    def __init__(self, *, service_name: str) -> None:
        self.registry = CollectorRegistry()
        # The registry belongs to one service instance, so repeating the service
        # name as a label only increases cardinality without adding information.
        self.service_name = service_name
        self.http_requests = Counter(
            "eap_http_requests_total",
            "HTTP requests processed by the platform.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "eap_http_request_duration_seconds",
            "HTTP request latency.",
            ("method", "route"),
            registry=self.registry,
        )
        self.runtime_tasks = Counter(
            "eap_runtime_tasks_total",
            "Runtime task terminal outcomes.",
            ("agent", "status"),
            registry=self.registry,
        )
        self.runtime_duration = Histogram(
            "eap_runtime_task_duration_seconds",
            "Successful Runtime task latency.",
            ("agent",),
            registry=self.registry,
        )
        self.tool_calls = Counter(
            "eap_tool_calls_total",
            "Tool invocation outcomes.",
            ("tool", "status"),
            registry=self.registry,
        )
        self.tool_duration = Histogram(
            "eap_tool_call_duration_seconds",
            "Successful Tool invocation latency.",
            ("tool",),
            registry=self.registry,
        )
        self.active_http_requests = Gauge(
            "eap_http_requests_active",
            "HTTP requests currently in progress.",
            registry=self.registry,
        )

    async def observe_event(self, event: Event) -> None:
        """Consume existing Runtime/Tool semantic events."""
        if event.type.startswith("runtime."):
            status = event.type.removeprefix("runtime.")
            if status in {
                "completed",
                "failed",
                "timeout",
                "cancelled",
            }:
                agent = self._bounded(
                    event.data.get("agent"),
                    fallback="unknown",
                )
                self.runtime_tasks.labels(
                    agent=agent,
                    status=status,
                ).inc()
                if status == "completed":
                    self.runtime_duration.labels(
                        agent=agent
                    ).observe(
                        max(
                            0.0,
                            float(event.data.get("elapsed", 0)),
                        )
                    )
            return
        if event.type.startswith("tool."):
            status = event.type.removeprefix("tool.")
            if status in {"completed", "failed"}:
                tool = self._bounded(
                    event.data.get("tool"),
                    fallback="unknown",
                )
                self.tool_calls.labels(
                    tool=tool,
                    status=status,
                ).inc()
                if status == "completed":
                    self.tool_duration.labels(
                        tool=tool
                    ).observe(
                        max(
                            0.0,
                            float(event.data.get("elapsed", 0)),
                        )
                    )

    def render(self) -> bytes:
        return generate_latest(self.registry)

    @staticmethod
    def _bounded(
        value: Any,
        *,
        fallback: str,
    ) -> str:
        """Limit label length; callers only pass registered component names."""
        normalized = str(value or fallback).strip()
        return normalized[:128] or fallback
