"""Durable PostgreSQL worker for asynchronous Agent tasks."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

from app.runtime.persistence import PostgreSQLTaskStore, RuntimeTaskLease
from app.runtime.runtime import Runtime

logger = logging.getLogger(__name__)


class RuntimeWorker:
    """Claim, heartbeat and execute durable Runtime tasks."""

    def __init__(
        self,
        store: PostgreSQLTaskStore,
        runtime: Runtime,
        *,
        worker_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 60,
        heartbeat_seconds: float = 15.0,
        concurrency: int = 4,
        max_attempts: int = 3,
    ) -> None:
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("Runtime heartbeat must be shorter than lease.")
        self.store = store
        self.runtime = runtime
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
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
                self._run(), name=f"runtime-worker:{self.worker_id}"
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def process_once(self) -> int:
        leases = await self.store.claim(
            worker_id=self.worker_id,
            limit=self.concurrency,
            lease_seconds=self.lease_seconds,
        )
        if not leases:
            return 0
        await asyncio.gather(
            *(self._execute(lease) for lease in leases),
            return_exceptions=True,
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
                logger.exception("Runtime worker polling failed; retrying.")
            if processed == 0:
                await asyncio.sleep(self.poll_interval_seconds)

    async def _execute(self, lease: RuntimeTaskLease) -> None:
        execution = asyncio.create_task(
            self.runtime.resume(lease.task),
            name=f"runtime-execution:{lease.task.task_id}",
        )
        heartbeat = asyncio.create_task(
            self._heartbeat(lease),
            name=f"runtime-heartbeat:{lease.task.task_id}",
        )
        try:
            done, _ = await asyncio.wait(
                {execution, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done:
                error = heartbeat.exception()
                if error is not None:
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                    raise error
            await execution
            await self.store.release(
                task_id=lease.task.task_id,
                worker_id=lease.worker_id,
                token=lease.token,
            )
        except asyncio.CancelledError:
            execution.cancel()
            raise
        except Exception as error:
            await self.store.abandon(
                task_id=lease.task.task_id,
                worker_id=lease.worker_id,
                token=lease.token,
                error=str(error),
                max_attempts=self.max_attempts,
            )
            logger.exception("Runtime task execution failed.")
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, lease: RuntimeTaskLease) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            renewed = await self.store.heartbeat(
                task_id=lease.task.task_id,
                worker_id=lease.worker_id,
                token=lease.token,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                raise RuntimeError(
                    f"Runtime worker lost task lease: {lease.task.task_id}"
                )
