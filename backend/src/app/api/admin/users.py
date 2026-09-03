"""用户管理路由（T20 / tech_design §3.11.1）：防锁死 + 留痕。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.auth.password import hash_password
from app.auth.tokens import UserContext
from app.database import get_session
from app.models import Role, User, UserRole
from app.rbac.service import invalidate_user_roles, load_user_ctx
from app.tracing import audit as audit_consts
from app.tracing.audit import write_audit
from app.utils.errors import ConflictError, NotFoundError, ValidationError, to_uni

router = APIRouter(
    prefix="/users", tags=["admin-users"],
    dependencies=[Depends(require_perm("adm:user.manage"))],
)


class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    nickname: Optional[str] = None
    initial_password: str = Field(..., min_length=10, max_length=128)
    role: str = "user"


class UserEdit(BaseModel):
    nickname: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(..., min_length=10, max_length=128)


def _user_dict(u: User, role_codes: list[str]) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "nickname": u.nickname,
        "status": u.status,
        "roles": role_codes,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("")
async def list_users(
    q: Optional[str] = None, role: Optional[str] = None, status: Optional[str] = None,
    cursor: Optional[str] = None, limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(User).order_by(User.created_at.desc()).limit(min(limit, 100))
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.nickname.ilike(f"%{q}%"))
    if status:
        stmt = stmt.where(User.status == status)
    rows = list((await session.execute(stmt)).scalars().all())
    out = []
    for u in rows:
        role_codes = (
            await session.execute(
                select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == u.id)
            )
        ).scalars().all()
        out.append(_user_dict(u, list(role_codes)))
    return to_uni({"items": out})


@router.post("")
async def create_user(
    body: UserCreate, ctx: UserContext = Depends(require_perm("adm:user.manage")),
    session: AsyncSession = Depends(get_session), request: Request = Request,
):
    ip = request.client.host if request and request.client else ""
    exists = await session.execute(select(User).where(User.email == body.email))
    if exists.scalars().first() is not None:
        raise ConflictError("邮箱已存在")
    if body.role not in ("user", "admin"):
        raise ValidationError("角色仅支持 user/admin")

    from app.domain.auth_service import validate_password_policy

    validate_password_policy(body.initial_password)
    user = User(
        email=body.email.strip().lower(),
        password_hash=hash_password(body.initial_password),
        nickname=body.nickname or "",
    )
    session.add(user)
    await session.flush()
    role_row = (await session.execute(select(Role).where(Role.code == body.role))).scalars().first()
    if role_row is None:
        raise NotFoundError("角色不存在")
    session.add(UserRole(user_id=user.id, role_id=role_row.id))
    await session.commit()
    await write_audit(
        actor_id=ctx.id, action=audit_consts.ADM_USER_CREATE,
        target_type="user", target_id=str(user.id), ip=ip,
        detail={"email": body.email, "role": body.role},  # 不含密码字面
    )
    invalidate_user_roles(str(user.id))
    return to_uni({"id": str(user.id), "email": user.email})


@router.patch("/{user_id}")
async def edit_user(
    user_id: str, body: UserEdit,
    ctx: UserContext = Depends(require_perm("adm:user.manage")),
    session: AsyncSession = Depends(get_session),
    request: Request = Request,
):
    ip = request.client.host if request and request.client else ""
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    # 防锁死（§3.11.1）
    if body.status == "disabled" and str(user.id) == ctx.id:
        raise ConflictError("不能禁用自身账号")

    if body.role is not None:
        current_roles = list(
            (await session.execute(
                select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
            )).scalars().all()
        )
        # 禁止移除最后一名 active admin
        if "admin" in current_roles and body.role != "admin":
            admin_count = await session.execute(
                select(func.count())
                .select_from(User)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.code == "admin", User.status == "active")
            )
            if admin_count.scalar() <= 1 and str(user.id) == ctx.id:
                raise ConflictError("不能移除最后一名管理员")
            # 移除 admin 角色
            role_ids = list(
                (await session.execute(select(Role.id).where(Role.code == "admin"))).scalars().all()
            )
            await session.execute(
                UserRole.__table__.delete().where(UserRole.user_id == user.id, UserRole.role_id.in_(role_ids))
            )
        elif body.role == "admin" and "admin" not in current_roles:
            role_row = (await session.execute(select(Role).where(Role.code == "admin"))).scalars().first()
            if role_row is not None:
                session.add(UserRole(user_id=user.id, role_id=role_row.id))

    if body.nickname is not None:
        user.nickname = body.nickname
    if body.status is not None:
        user.status = body.status
    await session.commit()
    await write_audit(
        actor_id=ctx.id, action=audit_consts.ADM_USER_UPDATE,
        target_type="user", target_id=user_id, ip=ip,
        detail={"email": user.email, "status": user.status, "role": body.role},
    )
    invalidate_user_roles(user_id)
    return to_uni({"id": user_id})


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: str, body: ResetPasswordIn,
    ctx: UserContext = Depends(require_perm("adm:user.manage")),
    session: AsyncSession = Depends(get_session),
    request: Request = Request,
):
    from app.domain.auth_service import validate_password_policy

    validate_password_policy(body.new_password)
    ip = request.client.host if request and request.client else ""
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    user.password_hash = hash_password(body.new_password)
    await session.commit()
    await write_audit(
        actor_id=ctx.id, action=audit_consts.ADM_USER_RESET_PASSWORD,
        target_type="user", target_id=user_id, ip=ip,
        detail={"email": user.email},  # 不含新密码
    )
    return to_uni({"ok": True})