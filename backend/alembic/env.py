"""Alembic 迁移环境（online/offline 双支持）。

生产与测试均走 app.database 的统一 DSN 管理。
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
import app.models as models  # noqa: F401  触发全部模型注册进 metadata
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # 允许命令行 -x dburl=... 覆盖（测试脚本用）
    url = config.get_main_option("sqlalchemy.url")
    try:
        db_url_opt = context.get_x_argument(as_dictionary=True).get("dburl")
    except Exception:  # noqa: S110, BLE001
        db_url_opt = None
    if db_url_opt:
        return db_url_opt
    try:
        return get_settings().database_url
    except Exception:
        return url or ""


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()