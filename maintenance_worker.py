"""独立数据生命周期维护Worker入口。"""

from __future__ import annotations

import asyncio

from app.bootstrap import Bootstrap


async def run_worker() -> None:
    platform = Bootstrap(
        {
            "retention_worker_enabled": True,
            "knowledge_ingestion_worker_enabled": False,
            "vector_outbox_worker_enabled": False,
            "workflow_worker_enabled": False,
        }
    ).build()
    app = platform.get_fastapi()
    async with app.router.lifespan_context(app):
        if platform.retention_worker is None:
            raise RuntimeError(
                "Maintenance worker requires system management database."
            )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
