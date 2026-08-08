"""Independent process entrypoint for durable asynchronous Agent tasks."""

from __future__ import annotations

import asyncio

from app.bootstrap import Bootstrap


async def run_worker() -> None:
    platform = Bootstrap(
        {
            "runtime_durable_queue_enabled": True,
            "runtime_worker_enabled": True,
            "workflow_worker_enabled": False,
            "vector_outbox_worker_enabled": False,
            "knowledge_ingestion_worker_enabled": False,
        }
    ).build()
    app = platform.get_fastapi()
    async with app.router.lifespan_context(app):
        if platform.runtime_worker is None:
            raise RuntimeError(
                "Runtime worker requires runtime_store_backend=postgresql."
            )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
