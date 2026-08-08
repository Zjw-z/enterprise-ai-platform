"""Independent process entrypoint for the transactional vector outbox."""

from __future__ import annotations

import asyncio

from app.bootstrap import Bootstrap


async def run_worker() -> None:
    """Use FastAPI lifespan so databases, Milvus and worker close cleanly."""
    platform = Bootstrap(
        {
            "vector_outbox_worker_enabled": True,
            "workflow_worker_enabled": False,
            "knowledge_ingestion_worker_enabled": False,
        }
    ).build()
    app = platform.get_fastapi()
    async with app.router.lifespan_context(app):
        if platform.vector_outbox_worker is None:
            raise RuntimeError(
                "Vector worker requires vector_store_backend=milvus "
                "and a configured embedding model."
            )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
