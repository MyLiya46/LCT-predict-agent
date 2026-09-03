"""权限查询服务（T07）：用户 → roles/perms 组装，进程内 TTL 缓存。

全应用唯一入口：T06 /auth/me 与中间件、require_perm 均从 load_user_ctx 取身份。
"""
from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import UserContext
from app.models import Permission, Role, RolePermission, UserRole

_CACHE: dict[str, tuple[float, UserContext]] = {}
_TTL_S = 30.0

ADMIN_PREFIX = "adm:"


def is_admin(ctx: UserContext) -> bool:
    """含任一 adm:* 权限或拥有 admin 角色即视为管理员。"""
    if any(role == "admin" for role in ctx.roles):
        return True
    return any(p.startswith(ADMIN_PREFIX) for p in ctx.perms)


def user_has_perm(ctx: UserContext, perm_code: str) -> bool:
    return perm_code in ctx.perms


def invalidate_user_roles(user_id: str) -> None:
    _CACHE.pop(str(user_id), None)


async def load_user_ctx(session: AsyncSession, user_id: str) -> UserContext:
    """组装 UserContext(id, email, nickname, roles, perms)。"""
    ukey = str(user_id)
    hit = _CACHE.get(ukey)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]

    from app.models import User

    user = await session.get(User, ukey)
    if user is None:
        return UserContext(ukey)

    roles_rows = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == ukey)
    )
    role_codes = list(roles_rows.scalars().all())

    perms_rows = await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == ukey)
    )
    perms = list(dict.fromkeys(perms_rows.scalars().all()))

    ctx = UserContext(user_id=ukey, email=user.email, nickname=user.nickname, roles=role_codes, perms=perms)
    _CACHE[ukey] = (time.monotonic(), ctx)
    return ctx