"""pytest 公共脚手架：PostgreSQL 测试库 fixture。

基础设施（PG + docker run postgres:16-alpine，见 README「数据库」）就绪后，
DATABASE_URL 指向专属测试库；fixture 每测试 drop/create schema 并 seed，互不残留。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 确保 src 与 backend 根在 path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_DEFAULT_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5432/agent_platform_test"
)


@pytest.fixture(scope="session", autouse=True)
def _env_setup() -> None:
    """测试环境变量固化（在 app.config 首次读取前生效）。

    `Settings` 会加载 cwd 下 backend/.env（真实凭据），此处将 LLM 引导变量清空，
    确保测试库由 seed 时不建真实 provider（引擎测试依赖 MockProvider 降级路径）。
    """
    os.environ["JWT_SECRET"] = "test_secret_" + "x" * 40
    os.environ["API_INTERNAL_TOKEN"] = "test_internal_token"
    os.environ["DATABASE_URL"] = _DEFAULT_TEST_DB_URL
    os.environ["LLM_API_KEYS"] = ""
    os.environ["LLM_BASE_URL"] = ""
    os.environ["LLM_DEFAULT_MODEL"] = ""


@pytest.fixture(scope="session", autouse=True)
async def _prepare_test_db():
    """session 层：确保专属测试库存在（连 postgres 元库 CREATE DATABASE IF NOT EXISTS）。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_url = _DEFAULT_TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    dbname = _DEFAULT_TEST_DB_URL.rsplit("/", 1)[-1]
    async with engine.begin() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    await engine.dispose()


@pytest.fixture()
async def db_session_factory():
    """专属 PG s测试库 + 全局引擎指向它。

    应用层（中间件/审计）write_audit 独立分支走全局 session_factory，因此
    fixture 通过 set_database_url 将全局引擎切到该测试库，避免跨测试残留。
    每测试 drop/create schema 后 create_all + seed，保证干净起点。
    """
    from sqlalchemy import text

    from app.database import get_session_factory, set_database_url
    from app.models import Base
    from seed.v1__base_seed import run_seed

    # NullPool：TestClient 请求在 anyio 独立循环，连接池跨循环会抛错
    set_database_url(_DEFAULT_TEST_DB_URL, null_pool=True)

    from app.database import setup_engine

    engine = setup_engine()
    async with engine.begin() as conn:
        # 每次测试重放干净 schema（asyncpg 需单语句执行）
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        await run_seed(session)
    yield factory

    from app.database import reset_engine

    reset_engine()