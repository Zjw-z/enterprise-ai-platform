"""Ordered application lifecycle with rollback and best-effort shutdown."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

LifecycleHook = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class LifecycleStep:
    """One named startup operation and its optional compensating cleanup."""

    name: str
    start: LifecycleHook
    stop: LifecycleHook | None = None


class ApplicationLifecycle:
    """Own startup ordering, failure rollback and idempotent shutdown."""

    def __init__(self) -> None:
        self._steps: list[LifecycleStep] = []
        self._finalizers: list[tuple[str, LifecycleHook]] = []
        self._started: list[LifecycleStep] = []
        self._running = False

    def add_step(
        self,
        name: str,
        start: LifecycleHook,
        stop: LifecycleHook | None = None,
    ) -> None:
        if self._running:
            raise RuntimeError("Cannot change a running lifecycle.")
        self._steps.append(LifecycleStep(name, start, stop))

    def add_finalizer(self, name: str, hook: LifecycleHook) -> None:
        if self._running:
            raise RuntimeError("Cannot change a running lifecycle.")
        self._finalizers.append((name, hook))

    async def startup(self) -> None:
        if self._running:
            return
        try:
            for step in self._steps:
                await self._invoke(step.start)
                self._started.append(step)
        except BaseException:
            await self._stop_started()
            await self._run_finalizers()
            raise
        self._running = True

    async def shutdown(self) -> None:
        if not self._running and not self._started:
            return
        self._running = False
        await self._stop_started()
        await self._run_finalizers()

    async def _stop_started(self) -> None:
        while self._started:
            step = self._started.pop()
            if step.stop is None:
                continue
            try:
                await self._invoke(step.stop)
            except BaseException:
                logger.exception(
                    "Application lifecycle cleanup failed: %s", step.name
                )

    async def _run_finalizers(self) -> None:
        # Finalizers are registered in their required shutdown order.  Unlike
        # step compensation they are not paired with startup operations.
        for name, hook in self._finalizers:
            try:
                await self._invoke(hook)
            except BaseException:
                logger.exception(
                    "Application lifecycle finalizer failed: %s", name
                )

    @staticmethod
    async def _invoke(hook: LifecycleHook) -> None:
        result = hook()
        if inspect.isawaitable(result):
            await result
