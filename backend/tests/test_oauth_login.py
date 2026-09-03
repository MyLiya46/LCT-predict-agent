"""T07 OA OAuth 双通道登录验收。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.auth import oauth
from app.database import get_session
from app.models import AuditLog, User
from app.utils.errors import ValidationError


def _oauth_settings():
    return SimpleNamespace(
        oauth_base_url="https://oauth.test",
        oauth_token_path="/oauth/token",
        oauth_grant_type="username",
        oauth_client_id="ai-client",
        oauth_client_secret="secret-value",
        oauth_source_type="app",
        oauth_user_type="P",
        oauth_login_field="username",
        oauth_device_id="",
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_access_token_accepts_direct_and_nested_payloads(monkeypatch):
    monkeypatch.setattr(oauth, "get_settings", _oauth_settings)
    route = respx.post("https://oauth.test/oauth/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "direct", "token_type": "Bearer", "expires_in": 60}),
            httpx.Response(200, json={"data": {"access_token": "nested", "expires_in": 120}}),
        ]
    )

    direct = await oauth.fetch_access_token("  TEST ")
    nested = await oauth.fetch_access_token("test")

    assert direct["access_token"] == "direct"
    assert nested["access_token"] == "nested"
    assert route.call_count == 2
    assert b"secret-value" in route.calls[0].request.content
    assert b"test" in route.calls[0].request.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"secret": "upstream-secret"}),
        httpx.Response(200, json={"data": {"token_type": "Bearer"}}),
    ],
)
@respx.mock
async def test_fetch_access_token_maps_upstream_errors_without_leaks(monkeypatch, response):
    monkeypatch.setattr(oauth, "get_settings", _oauth_settings)
    respx.post("https://oauth.test/oauth/token").mock(return_value=response)

    with pytest.raises(ValidationError) as exc_info:
        await oauth.fetch_access_token("test")

    assert exc_info.value.message == "OA 登录失败：OAuth 网关未通过验证"
    assert "upstream-secret" not in str(exc_info.value)



async def _request_app(factory, monkeypatch, token_result=None, side_effect=None):
    from app.domain import auth_service
    from app.main import create_app

    fetch = AsyncMock(return_value=token_result, side_effect=side_effect)
    monkeypatch.setattr(auth_service, "fetch_access_token", fetch)
    app = create_app()

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    return app, client, fetch


@pytest.mark.asyncio
async def test_oa_login_returns_dual_tokens_and_backup_me(db_session_factory, monkeypatch):
    oauth_token = {"access_token": "gateway-token", "token_type": "Bearer", "expires_in": 3600}
    app, client, fetch = await _request_app(db_session_factory, monkeypatch, oauth_token)
    try:
        response = await client.post(
            "/api/auth/login", json={"oa": "  TEST  "}, headers={"user-agent": "test-agent"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["oa"] == "test"
        assert data["oauth_access_token"] == "gateway-token"
        assert data["access_token"] and data["refresh_token"]
        assert set(data) == {
            "oa", "access_token", "refresh_token", "token_type", "expires_in",
            "oauth_access_token", "oauth_token_type", "oauth_expires_in",
        }
        fetch.assert_awaited_once_with(username="test")

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert me.status_code == 200
        assert "user" in me.json()["data"]["roles"]
        assert "chat:read" in me.json()["data"]["perms"]
        assert "chat:send" in me.json()["data"]["perms"]
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    async with db_session_factory() as session:
        user = (await session.execute(select(User).where(User.oa == "test"))).scalars().one()
        assert user.email == "test@tcl.com"
        audit_row = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "auth.login", AuditLog.target_id == str(user.id))
            )
        ).scalars().first()
        assert audit_row is not None
        assert audit_row.detail == {"oa": "test"}


@pytest.mark.asyncio
async def test_oa_login_is_idempotent_for_concurrent_normalized_oa(db_session_factory, monkeypatch):
    oauth_token = {"access_token": "gateway-token", "token_type": "Bearer", "expires_in": 3600}
    app, client, fetch = await _request_app(db_session_factory, monkeypatch, oauth_token)
    try:
        responses = await asyncio.gather(*[
            client.post("/api/auth/login", json={"oa": "Test"}),
            client.post("/api/auth/login", json={"oa": " test "}),
        ])
        assert [r.status_code for r in responses] == [200, 200]
        assert all(r.json()["access_token"] for r in responses)
        assert fetch.await_count == 2
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    async with db_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(User).where(User.oa == "test"))
        assert count == 1


@pytest.mark.asyncio
async def test_oa_login_gateway_failure_is_safe_and_audited(db_session_factory, monkeypatch):
    error = ValidationError("OA 登录失败：OAuth 网关未通过验证")
    app, client, _ = await _request_app(db_session_factory, monkeypatch, side_effect=error)
    try:
        response = await client.post("/api/auth/login", json={"oa": "Test"})
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "400_VALIDATION"
        assert body["message"] == "OA 登录失败：OAuth 网关未通过验证"
        assert "secret" not in response.text
        assert "access_token" not in response.text
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    async with db_session_factory() as session:
        rows = (
            await session.execute(select(AuditLog).where(AuditLog.action == "auth.login_failed"))
        ).scalars().all()
        assert any(row.detail == {"oa": "test"} for row in rows)
