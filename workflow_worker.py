"""Independent process entrypoint for distributed Workflow execution."""

from __future__ import annotations

import asyncio

from app.bootstrap import Bootstrap


async def run_worker() -> None:
    platform = Bootstrap(
        {
            "workflow_worker_enabled": True,
            "vector_outbox_worker_enabled": False,
            "knowledge_ingestion_worker_enabled": False,
        }
    ).build()
    app = platform.get_fastapi()
    async with app.router.lifespan_context(app):
        if platform.workflow_worker is None:
            raise RuntimeError(
                "Workflow worker requires workflow_backend=postgresql."
            )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
