"""T05 异常框架单测：七错误码映射、统一 JSON、500 兜底、request-id 透传。"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.request_id import RequestIDMiddleware
from app.utils.errors import ApiError, NotFoundError, register_exception_handlers, to_uni


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/not-found")
    async def _not_found():
        raise NotFoundError("目标不存在")

    @app.get("/conflict")
    async def _conflict():
        raise ApiError(code="409_CONFLICT", message="冲突", status_code=409)

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("inner boom")

    @app.get("/ok")
    async def _ok():
        return to_uni({"a": 1})

    return app


def test_not_found_mapping():
    with TestClient(build_app()) as c:
        resp = c.get("/not-found")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "404_NOT_FOUND"
        assert "不存在" in body["message"]


def test_unknown_exception_500():
    with TestClient(build_app(), raise_server_exceptions=False) as c:
        resp = c.get("/boom")
        assert resp.status_code == 500
        assert resp.json()["code"] == "500_INTERNAL"


def test_request_id_roundtrip():
    with TestClient(build_app()) as c:
        rid = str(uuid.uuid4())
        resp = c.get("/ok", headers={"X-Request-Id": rid})
        assert resp.headers.get("X-Request-Id") == rid
        assert resp.json()["data"] == {"a": 1}


def test_auto_request_id():
    with TestClient(build_app()) as c:
        resp = c.get("/ok")
        assert resp.headers.get("X-Request-Id")


def test_to_uni():
    body = to_uni({"x": 1}, message="good")
    assert body == {"code": "0", "message": "good", "data": {"x": 1}}