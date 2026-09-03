"""T01 冒烟测试：应用可启动，/healthz /readyz 返回 200。

（T01 阶段为 {"status":"ok"}；T18 后为聚合健康检查，断言 status 字段。）
"""

import os

from fastapi.testclient import TestClient

_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5432/agent_platform_test"
)
os.environ["DATABASE_URL"] = _TEST_DB_URL

from app.main import app  # noqa: E402


def test_healthz():
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "checks" in body


def test_readyz():
    with TestClient(app) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 200