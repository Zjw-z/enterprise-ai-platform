"""Distributed Workflow worker with leases, heartbeats and fencing."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

from app.workflow.executor import WorkflowExecutor
from app.workflow.store import (
    WorkflowLease,
    WorkflowLeaseLost,
    WorkflowLeaseStore,
)

logger = logging.getLogger(__name__)


class WorkflowWorker:
    """Claim durable executions and run them through WorkflowExecutor."""

    def __init__(
        self,
        store: WorkflowLeaseStore,
        executor: WorkflowExecutor,
        *,
        worker_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 60,
        heartbeat_seconds: float = 15.0,
        concurrency: int = 4,
        max_attempts: int = 8,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError(
                "Workflow worker poll interval must be positive."
            )
        if lease_seconds < 3:
            raise ValueError(
                "Workflow worker lease must be at least 3 seconds."
            )
        if (
            heartbeat_seconds <= 0
            or heartbeat_seconds >= lease_seconds
        ):
            raise ValueError(
                "Workflow heartbeat must be positive and shorter "
                "than the lease."
            )
        if concurrency < 1:
            raise ValueError(
                "Workflow worker concurrency must be positive."
            )
        if max_attempts < 1:
            raise ValueError(
                "Workflow worker max_attempts must be positive."
            )
        self.store = store
        self.executor = executor
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{os.getpid()}:"
            f"{uuid.uuid4().hex[:8]}"
        )
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.concurrency = concurrency
        self.max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name=f"workflow-worker:{self.worker_id}",
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def process_once(self) -> int:
        leases = await self.store.claim(
            worker_id=self.worker_id,
            limit=self.concurrency,
            lease_seconds=self.lease_seconds,
        )
        if not leases:
            return 0
        outcomes = await asyncio.gather(
            *(self._execute(lease) for lease in leases),
            return_exceptions=True,
        )
        for lease, outcome in zip(leases, outcomes, strict=True):
            if isinstance(outcome, Exception):
                await self.store.abandon(
                    execution_id=lease.execution.execution_id,
                    worker_id=lease.worker_id,
                    token=lease.token,
                    error=str(outcome),
                    max_attempts=self.max_attempts,
                )
                logger.error(
                    "Workflow execution failed in worker %s: %s",
                    self.worker_id,
                    lease.execution.execution_id,
                    exc_info=(
                        type(outcome),
                        outcome,
                        outcome.__traceback__,
                    ),
                )
        return len(leases)

    async def _run(self) -> None:
        while True:
            try:
                processed = await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                processed = 0
                logger.exception(
                    "Workflow worker polling failed; retrying."
                )
            if processed == 0:
                await asyncio.sleep(self.poll_interval_seconds)

    async def _execute(
        self,
        lease: WorkflowLease,
    ) -> None:
        execution_id = lease.execution.execution_id
        execution_task = asyncio.create_task(
            self.executor.resume(execution_id),
            name=f"workflow-execution:{execution_id}",
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat(lease),
            name=f"workflow-heartbeat:{execution_id}",
        )
        completed = False
        try:
            done, _ = await asyncio.wait(
                {execution_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                error = heartbeat_task.exception()
                if error is not None:
                    execution_task.cancel()
                    await asyncio.gather(
                        execution_task,
                        return_exceptions=True,
                    )
                    raise error
            await execution_task
            completed = True
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(
                heartbeat_task,
                return_exceptions=True,
            )
            if completed:
                await self.store.release(
                    execution_id=execution_id,
                    worker_id=lease.worker_id,
                    token=lease.token,
                )

    async def _heartbeat(
        self,
        lease: WorkflowLease,
    ) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            renewed = await self.store.heartbeat(
                execution_id=lease.execution.execution_id,
                worker_id=lease.worker_id,
                token=lease.token,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                raise WorkflowLeaseLost(
                    "Workflow worker lost its lease: "
                    f"{lease.execution.execution_id}"
                )
