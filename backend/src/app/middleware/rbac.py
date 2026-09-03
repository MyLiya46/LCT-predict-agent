"""AdminPrefixMiddleware：/api/v1/admin/** 类级硬化（T07）。

免去逐路由挂点：token 缺失 → 401；权限不足 → 403 + 写 authz.denied 审计。
白名单路径（健康检查等）不在 /admin 前缀下，不受影响。
"""
from __future__ import annotations

from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.auth.tokens import decode_token
from app.rbac.service import is_admin

ADMIN_PREFIX = "/api/v1/admin/"


class AdminPrefixMiddleware(BaseHTTPMiddleware):
    """对 /admin/** 做类级鉴权。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(ADMIN_PREFIX):
            # 硬编码状态机：无 token → 401；token 合法但非 admin → 403+审计
            auth = request.headers.get("Authorization", "")
            token = auth[7:].strip() if auth.startswith("Bearer ") else None
            if not token:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=401,
                    content={"code": "401_UNAUTHORIZED", "message": "未提供认证令牌", "data": None},
                )
            try:
                claims = decode_token(token)
            except Exception:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=401,
                    content={"code": "401_UNAUTHORIZED", "message": "令牌无效或已过期", "data": None},
                )
            # 权限校验：非 admin → 403 + 审计
            if claims.get("token_type") != "access" or not is_admin(
                _CtxProxy(claims)
            ):
                from app.tracing.audit import write_audit
                from fastapi.responses import JSONResponse

                await write_audit(
                    actor_id=claims.get("sub"),
                    actor_email=claims.get("email", ""),
                    action="authz.denied",
                    target_type="api",
                    target_id=claims.get("sub"),
                    ip=request.client.host if request.client else "",
                    detail={
                        "reason": "permission_denied",
                        "path": path,
                        "method": request.method,
                        "perm": "adm:*",
                    },
                )
                return JSONResponse(
                    status_code=403,
                    content={"code": "403_FORBIDDEN", "message": "权限不足", "data": None},
                )
        return await call_next(request)


class _CtxProxy:
    """用 claims 构造轻量身份（给 is_admin 判断）。"""

    def __init__(self, claims: dict) -> None:
        self.roles = claims.get("roles", [])
        self.perms = claims.get("perms", [])