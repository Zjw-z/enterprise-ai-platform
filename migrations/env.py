"""Alembic environment for the system-management database."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

import yaml
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.agent import configuration as _agent_configuration  # noqa: F401
from app.agent import governance_store as _agent_governance  # noqa: F401
from app.core import audit as _audit_models  # noqa: F401
from app.knowledge import models as _knowledge_models  # noqa: F401
from app.llm import configuration as _llm_configuration  # noqa: F401
from app.llm import usage_store as _llm_usage  # noqa: F401
from app.runtime import persistence as _runtime_persistence  # noqa: F401
from app.system.models import SystemBase
from app.system import approval_store as _approval_store  # noqa: F401
from app.tool import configuration as _tool_configuration  # noqa: F401
from app.vector import outbox as _vector_outbox  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def resolve_database_url() -> str:
    """优先读环境变量，否则按config.yaml选择对应环境配置。"""
    database_url = os.getenv("EAP_SYSTEM_DATABASE_URL")
    if database_url:
        return database_url

    project_root = Path(__file__).resolve().parents[1]
    selector_path = Path(
        os.getenv(
            "EAP_CONFIG_FILE",
            str(project_root / "config.yaml"),
        )
    )
    with selector_path.open(encoding="utf-8") as stream:
        selector = yaml.safe_load(stream) or {}
    environment = os.getenv(
        "EAP_ENVIRONMENT",
        str(selector.get("environment", "test")),
    )
    environment_path = (
        selector_path.parent
        / f"config.{environment}.yaml"
    )
    with environment_path.open(encoding="utf-8") as stream:
        environment_config = yaml.safe_load(stream) or {}
    database_url = environment_config.get(
        "system_database_url"
    )
    if not database_url:
        raise RuntimeError(
            "system_database_url is required for migrations."
        )
    return str(database_url)


# ConfigParser把百分号用于插值，密码URL编码中的百分号必须转义。
config.set_main_option(
    "sqlalchemy.url",
    resolve_database_url().replace("%", "%%"),
)
selected_url = config.get_main_option("sqlalchemy.url")
if selected_url.startswith("sqlite+aiosqlite:///"):
    database_path = selected_url.removeprefix(
        "sqlite+aiosqlite:///"
    )
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

target_metadata = SystemBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
