"""数据库引擎与会话工厂（SQLAlchemy 2 async）。

生产/开发/测试统一走 PostgreSQL（asyncpg 连接池）；DSN 由 settings.database_url 提供。
测试通过 set_database_url 覆盖为测试库。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

logger = logging.getLogger("app.db")

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_test_override_url: Optional[str] = None
_test_null_pool: bool = False


def get_database_url() -> str:
    if _test_override_url:
        return _test_override_url
    return get_settings().database_url


def set_database_url(url: str, *, null_pool: bool = False) -> None:
    """测试用：覆盖 DSN（必须早于引擎创建）。

    null_pool=True 时引擎使用 NullPool（每请求独立连接）：TestClient 请求跑在
    anyio 单独事件循环，连接池跨循环会「Future attached to a different loop」；
    NullPool 无跨循环复用，适配该场景。
    """
    global _test_override_url, _test_null_pool
    _test_override_url = url
    _test_null_pool = null_pool
    reset_engine()


def setup_engine() -> AsyncEngine:
    """创建/复用全局 async engine + session factory。"""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    url = get_database_url()
    if _test_null_pool:
        from sqlalchemy.pool import NullPool

        _engine = create_async_engine(url, poolclass=NullPool, pool_pre_ping=False)
    else:
        _engine = create_async_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("database engine created: %s", url.split("@")[-1])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        setup_engine()
    assert _session_factory is not None
    return _session_factory


def get_sync_session_maker() -> sessionmaker:
    """同步 session maker（Alembic offline/并行任务，可选）。"""
    engine = setup_engine()
    return sessionmaker(bind=engine.sync_engine, expire_on_commit=False)


def reset_engine() -> None:
    """测试用：销毁现有引擎（配合 set_database_url；同步 dispose 免事件循环依赖）。"""
    global _engine, _session_factory
    if _engine is not None:
        try:
            _engine.sync_engine.dispose()
        except Exception:  # noqa: S110, BLE001
            try:
                import asyncio

                asyncio.get_event_loop().run_until_complete(_engine.dispose())
            except Exception:  # noqa: S110
                pass
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级 session。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session