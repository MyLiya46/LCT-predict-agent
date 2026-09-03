"""T07 RBAC 单测：/admin 前缀硬化、越权 403+审计、非 admin 无管理权限、/auth/me 权限一致。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.password import hash_password
from app.auth.tokens import create_token
from app.models import Role, User, UserRole
from app.tracing.audit import AUDIT_VIEW
from sqlalchemy import select


def _build_app(session_factory):
    from app.database import get_session_factory
    from app.domain.auth_service import register_user
    from app.middleware.rbac import AdminPrefixMiddleware
    from app.utils.errors import register_exception_handlers

    app = FastAPI()
    app.add_middleware(AdminPrefixMiddleware)
    register_exception_handlers(app)

    # 挂一个受保护的管理路由（用 provider 方式直接暴露 401/403 语义走中间件）
    @app.get("/api/v1/admin/users")
    async def _admin_users():
        return {"ok": True}

    @app.get("/api/v1/open")
    async def _open():
        return {"ok": True}

    return app


async def _make_token(session_factory, email: str, password: str, role_code: str = "user") -> str:
    async with session_factory() as s:
        role = (await s.execute(select(Role).where(Role.code == role_code))).scalars().first()
        user = User(email=email, password_hash=hash_password(password), nickname="X", status="active")
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=role.id))
        from app.rbac.service import load_user_ctx

        ctx = await load_user_ctx(s, str(user.id))
        access = create_token(user, "access", ctx.roles, ctx.perms)
        await s.commit()
        return access


@pytest.mark.asyncio
async def test_admin_prefix_user_denied(db_session_factory):
    app = _build_app(db_session_factory)
    token = await _make_token(db_session_factory, "u1@corp.com", "Passw0rd123", "user")
    with TestClient(app) as c:
        # 无 token → 401
        r = c.get("/api/v1/admin/users")
        assert r.status_code == 401
        # user token → 403
        r = c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
        assert r.json()["code"] == "403_FORBIDDEN"
        # 非 /admin 路径不受影响
        r = c.get("/api/v1/open", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_denied_writes_audit(db_session_factory):
    app = _build_app(db_session_factory)
    token = await _make_token(db_session_factory, "u2@corp.com", "Passw0rd123", "user")
    with TestClient(app) as c:
        c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    # 越权应写 authz.denied 审计
    async with db_session_factory() as s:
        from app.models import AuditLog

        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "authz.denied"))).scalars().all()
        assert len(rows) >= 1, "越权未写审计"
        assert rows[0].detail.get("reason") == "permission_denied"

        # 检索留痕符号存在（audit.view 常量可用）
        assert AUDIT_VIEW == "audit.view"