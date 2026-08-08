"""Async database lifecycle for the system-management control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.system.models import SystemBase


class SystemDatabase:
    def __init__(
        self,
        url: str,
        *,
        schema_mode: str = "create_all",
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout_seconds: float = 30.0,
    ) -> None:
        if not url:
            raise ValueError(
                "System database URL cannot be empty."
            )
        if schema_mode not in {"create_all", "validate"}:
            raise ValueError(
                "System database schema_mode must be "
                "'create_all' or 'validate'."
            )
        if url.startswith("sqlite+aiosqlite:///"):
            database = url.removeprefix(
                "sqlite+aiosqlite:///"
            )
            if database != ":memory:":
                Path(database).parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
        self.url = url
        self.schema_mode = schema_mode
        engine_options = {"pool_pre_ping": True}
        if not url.startswith("sqlite+aiosqlite:"):
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout_seconds,
            )
        self.engine: AsyncEngine = create_async_engine(
            url,
            **engine_options,
        )
        self.sessions = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def initialize(self) -> None:
        if self.schema_mode == "validate":
            await self.validate_schema()
            return
        async with self.engine.begin() as connection:
            await connection.run_sync(
                SystemBase.metadata.create_all
            )

    async def health_check(self) -> None:
        """验证数据库连接可用，不泄露连接凭据。"""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def validate_schema(self) -> None:
        """启动时确认系统表已经通过迁移部署。"""
        async with self.engine.connect() as connection:
            existing = await connection.run_sync(
                lambda sync_connection: set(
                    inspect(sync_connection).get_table_names()
                )
            )
        required = set(SystemBase.metadata.tables)
        missing = sorted(required - existing)
        if missing:
            raise RuntimeError(
                "System database schema is not migrated; "
                "missing tables: "
                + ", ".join(missing)
                + ". Run 'alembic upgrade head' first."
            )

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
