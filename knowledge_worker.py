"""独立知识库文档解析Worker进程入口。"""

from __future__ import annotations

import asyncio

from app.bootstrap import Bootstrap


async def run_worker() -> None:
    """复用平台生命周期初始化数据库、MinIO与解析依赖。"""
    platform = Bootstrap(
        {
            "knowledge_ingestion_worker_enabled": True,
            "vector_outbox_worker_enabled": False,
            "workflow_worker_enabled": False,
        }
    ).build()
    app = platform.get_fastapi()
    async with app.router.lifespan_context(app):
        ingestion = platform.knowledge_ingestion_service
        if ingestion is None or not ingestion.worker_enabled:
            raise RuntimeError(
                "Knowledge worker requires PostgreSQL, MinIO and "
                "a configured document parser."
            )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
