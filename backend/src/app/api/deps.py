"""FastAPI 鉴权依赖（T06 解析 JWT → UserContext；T07 叠加 RBAC + 越权审计）。"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import UserContext, decode_token
from app.database import get_session
from app.rbac.service import is_admin, load_user_ctx, user_has_perm
from app.utils.errors import ForbiddenError, UnauthorizedError

BEARER_PREFIX = "Bearer "


def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith(BEARER_PREFIX):
        return auth[len(BEARER_PREFIX):].strip()
    return None


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> UserContext:
    """JWT → 当前用户身份（403/401 语义；无令牌 401 不写审计）。"""
    token = _extract_bearer(request)
    if not token:
        raise UnauthorizedError("未提供认证令牌")
    claims = decode_token(token)
    if claims.get("token_type") != "access":
        raise UnauthorizedError("令牌类型错误")
    user_id = claims.get("sub")
    if not user_id:
        raise UnauthorizedError("令牌载荷非法")
    ctx = await load_user_ctx(session, user_id)
    return ctx


def require_perm(perm_code: str):
    """权限点依赖：无权限 → ForbiddenError + 主动写 authz.denied 审计。"""

    async def _dep(request: Request, ctx: UserContext = Depends(get_current_user)) -> UserContext:
        if not user_has_perm(ctx, perm_code) and not (perm_code.startswith("adm:") and is_admin(ctx)):
            raise ForbiddenError(
                f"缺少权限 {perm_code}",
                audit_ctx={
                    "actor_id": ctx.id,
                    "actor_email": ctx.email,
                    "action": "authz.denied",
                    "target_type": "api",
                    "target_id": None,
                    "ip": request.client.host if request.client else "",
                    "reason": "permission_denied",
                    "path": request.url.path,
                    "method": request.method,
                    "extra": {"perm": perm_code},
                },
            )
        return ctx

    return _dep


def require_owner(conversation_id: str):
    """owner 数据级校验骨架（T17 落具体查询）。

    语义（tech_design §3.3）：越权/不存在 → 404_NOT_FOUND，不泄露存在性。
    这里仅约定接口；T17 提供真实实现对会话/消息做 owner 查询。
    """

    async def _dep(ctx: UserContext = Depends(get_current_user)) -> UserContext:
        return ctx

    return _dep