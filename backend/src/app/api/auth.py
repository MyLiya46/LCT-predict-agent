"""认证路由（T06 / tech_design §3.1 接口表）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.tokens import UserContext
from app.database import get_session
from app.domain.auth_service import (
    change_password,
    login_by_oa,
    login_user,
    logout_user,
    refresh_login,
    register_user,
    update_nickname,
)
from app.utils.errors import ValidationError, to_uni

router = APIRouter(prefix="/auth", tags=["auth"])
oa_router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str = Field(..., max_length=255)
    # 口令政策（长度/大小写数字）统一由 service 层 validate_password_policy 校验，
    # 返回 400_VALIDATION + 可读 message（T27）；pydantic 不设 min_length 避免 422 技术文案
    password: str = Field(..., max_length=128)
    nickname: Optional[str] = None


class LoginIn(BaseModel):
    email: str
    password: str


class OaLoginIn(BaseModel):
    oa: str = Field(..., min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


class NicknameUpdateIn(BaseModel):
    nickname: str = Field(..., max_length=32)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/register")
async def register(
    body: RegisterIn, request: Request, session: AsyncSession = Depends(get_session)
):
    user = await register_user(
        session, email=body.email, password=body.password, nickname=body.nickname or "",
        ip=_client_ip(request),
    )
    return to_uni({"user_id": str(user.id), "email": user.email})


@router.post("/login")
async def login(
    body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)
):
    data = await login_user(
        session, email=body.email, password=body.password,
        ip=_client_ip(request), user_agent=request.headers.get("user-agent", ""),
    )
    return to_uni(data)


@oa_router.post("/login")
async def oa_login(
    body: OaLoginIn, request: Request, session: AsyncSession = Depends(get_session)
):
    return await login_by_oa(
        session, body.oa, ip=_client_ip(request), user_agent=request.headers.get("user-agent", "")
    )


@router.get("/me")
async def me(
    ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # T28：昵称等资料以库中实时值为准（JWT claims 中 nickname 是签发时快照）
    from app.models import User

    user = await session.get(User, ctx.id)
    d = ctx.to_dict()
    if user is not None:
        d["nickname"] = user.nickname
        d["email"] = user.email
    return to_uni(d)


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request, session: AsyncSession = Depends(get_session)):
    data = await refresh_login(
        session, body.refresh_token,
        ip=_client_ip(request), user_agent=request.headers.get("user-agent", ""),
    )
    return to_uni(data)


@router.post("/logout")
async def logout(
    request: Request,
    x_refresh_token: Optional[str] = Header(default=None, alias="X-Refresh-Token"),
    ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not x_refresh_token:
        raise ValidationError("缺少 X-Refresh-Token 头")
    await logout_user(session, x_refresh_token, actor_id=ctx.id)
    return to_uni({"ok": True})


@router.patch("/password")
async def password_change(
    body: PasswordChangeIn,
    ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await change_password(session, user_id=ctx.id, old_password=body.old_password, new_password=body.new_password)
    return to_uni({"ok": True})


@router.patch("/me")
async def update_me(
    body: NicknameUpdateIn,
    ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user = await update_nickname(session, user_id=ctx.id, nickname=body.nickname)
    return to_uni({"id": str(user.id), "nickname": user.nickname})
