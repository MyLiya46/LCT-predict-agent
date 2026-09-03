"""T11 管理端 API 契约、RBAC 和越权审计验收。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.password import hash_password
from app.auth.tokens import create_token
from app.models import Role, User, UserRole


async def _make_token(session_factory, email: str, role_code: str) -> str:
    async with session_factory() as session:
        role = (await session.execute(select(Role).where(Role.code == role_code))).scalars().one()
        user = User(
            email=email,
            password_hash=hash_password("AdminTest12345"),
            nickname=role_code,
            status="active",
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.flush()
        from app.rbac.service import load_user_ctx

        ctx = await load_user_ctx(session, str(user.id))
        token = create_token(user, "access", ctx.roles, ctx.perms)
        await session.commit()
        return token


@pytest.mark.asyncio
async def test_admin_modules_rbac_and_schema(db_session_factory):
    from app.main import create_app

    admin = await _make_token(db_session_factory, "t11-admin@corp.com", "admin")
    user = await _make_token(db_session_factory, "t11-user@corp.com", "user")
    admin_headers = {"Authorization": f"Bearer {admin}"}
    user_headers = {"Authorization": f"Bearer {user}"}

    readonly_paths = [
        "/api/v1/admin/users",
        "/api/v1/admin/tools",
        "/api/v1/admin/datasources",
        "/api/v1/admin/scenarios",
        "/api/v1/admin/llm",
        "/api/v1/admin/audits",
        "/api/v1/admin/config",
    ]
    with TestClient(create_app()) as client:
        for path in readonly_paths:
            response = client.get(path, headers=admin_headers)
            assert response.status_code == 200, (path, response.text)
            body = response.json()
            assert {"code", "message", "data"}.issubset(body), (path, body)

        # Class-level middleware denies a regular user once, with one audit row.
        denied = client.get("/api/v1/admin/users", headers=user_headers)
        assert denied.status_code == 403
        assert denied.json()["code"] == "403_FORBIDDEN"
        assert client.get("/api/v1/admin/users").status_code == 401
        assert client.get(
            "/api/v1/admin/users",
            headers={"Authorization": "Bearer oauth_access_token_only"},
        ).status_code == 401

        # Invalid payloads exercise the write schemas without changing data.
        for method, path in [
            ("post", "/api/v1/admin/users"),
            ("post", "/api/v1/admin/tools"),
            ("post", "/api/v1/admin/datasources"),
            ("post", "/api/v1/admin/llm"),
            ("patch", "/api/v1/admin/config"),
        ]:
            response = getattr(client, method)(path, headers=admin_headers, json={})
            assert response.status_code in (400, 422), (method, path, response.text)

    async with db_session_factory() as session:
        from app.models import AuditLog

        denied_rows = (
            await session.execute(select(AuditLog).where(AuditLog.action == "authz.denied"))
        ).scalars().all()
        assert len(denied_rows) == 1
        assert denied_rows[0].detail.get("reason") == "permission_denied"
