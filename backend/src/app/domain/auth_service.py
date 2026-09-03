"""认证用例（T06）：注册/登录/刷新/登出/改密/me。"""
from __future__ import annotations

import secrets
import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.lockout import (
    assert_not_locked,
    clear_login_failures,
    record_login_failure,
)
from app.auth.oauth import OA_LOGIN_FAILED_MESSAGE, fetch_access_token, normalize_oa
from app.auth.password import hash_password, verify_password
from app.auth.tokens import (
    UserContext,
    create_token,
    decode_token,
    hash_refresh_token,
)
from app.config_service import get_sys_config
from app.models import RefreshToken, Role, User, UserRole
from app.rbac.service import load_user_ctx
from app.tracing import audit
from app.tracing.audit import write_audit as _write_audit
from app.utils.errors import ConflictError, NotFoundError, UnauthorizedError, ValidationError

MIN_PASSWORD_LEN = 10


class PasswordPolicyError(ValidationError):
    """口令政策失败（T27）：继承 ApiError → 400_VALIDATION + 可读 message，不再落 500。"""
    pass


def validate_password_policy(pw: str) -> None:
    """口令政策（tech_design §3.1）：≥10 位含大小写与数字。"""
    if len(pw) < MIN_PASSWORD_LEN:
        raise PasswordPolicyError("密码长度至少 10 位")
    if not any(c.islower() for c in pw) or not any(c.isupper() for c in pw) or not any(c.isdigit() for c in pw):
        raise PasswordPolicyError("密码必须同时包含大小写字母与数字")


async def _get_role_by_code(session: AsyncSession, code: str) -> Optional[Role]:
    res = await session.execute(select(Role).where(Role.code == code))
    return res.scalars().first()


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    nickname: str = "",
    ip: str = "",
) -> User:
    """白名单邮箱注册。已存在 → 409；成功角色=user。"""
    validate_password_policy(password)

    email = email.strip().lower()
    suffixes = await get_sys_config(session, "auth.email_whitelist_suffixes", ["@corp.com"])
    if not any(email.endswith(sfx) for sfx in suffixes):
        from app.utils.errors import ValidationError

        raise ValidationError(f"邮箱后缀不在白名单内（允许：{'、'.join(suffixes)}）")

    exists = await session.execute(select(User).where(User.email == email))
    if exists.scalars().first() is not None:
        raise ConflictError("该邮箱已注册")

    user = User(email=email, password_hash=hash_password(password), nickname=nickname or email.split("@")[0])
    session.add(user)
    await session.flush()
    role = await _get_role_by_code(session, "user")
    if role is None:
        raise NotFoundError("预置角色 user 未初始化")
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()

    await write_audit_entry(
        actor_id=str(user.id), actor_email=email, action=audit.AUTH_REGISTER,
        target_type="user", target_id=str(user.id), ip=ip,
        detail={"email": email}, session=session,
    )
    await session.refresh(user)
    return user


async def _issue_tokens(
    session: AsyncSession, user: User, ctx: UserContext, refresh_token_id: Optional[uuid.UUID] = None
) -> dict:
    """签发 access + refresh，refresh 落库（哈希）。"""
    access = create_token(user, "access", ctx.roles, ctx.perms)
    ret = {"access_token": access, "expires_in": 15 * 60}
    if refresh_token_id is None:
        refresh_id = uuid.uuid4()
    else:
        refresh_id = refresh_token_id
    refresh = create_token(user, "refresh", ctx.roles, ctx.perms, jti=str(refresh_id))
    ret["refresh_token"] = refresh
    return ret


async def _store_refresh(
    session: AsyncSession,
    *,
    user_id: str,
    refresh_jwt: str,
    ref_id: uuid.UUID,
    ip: str = "",
    user_agent: str = "",
    replaced_by: Optional[uuid.UUID] = None,
) -> None:
    """refresh 落库（SHA-256 哈希；轮换时置旧行 revoked/replaced_by）。"""
    token_hash = hash_refresh_token(refresh_jwt)
    expires = decode_token(refresh_jwt)["exp"]
    import datetime as _dt

    session.add(
        RefreshToken(
            id=str(ref_id),
            user_id=str(user_id),
            token_hash=token_hash,
            expires_at=_dt.datetime.fromtimestamp(expires, tz=_dt.timezone.utc),
            ip=ip,
            user_agent=user_agent,
        )
    )
    await session.flush()


async def login_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    ip: str = "",
    user_agent: str = "",
) -> dict:
    """登录：账户锁 → 校验 → 签发双令牌。"""
    email = email.strip().lower()
    fail_limit = await get_sys_config(session, "auth.login_fail_limit", 5)
    assert_not_locked(email, int(fail_limit))

    res = await session.execute(select(User).where(User.email == email))
    user = res.scalars().first()

    if user is None or not verify_password(password, user.password_hash):
        record_login_failure(email)
        await write_audit_entry(
            actor_email=email, action=audit.AUTH_LOGIN_FAILED, ip=ip, detail={"email": email}
        )
        raise UnauthorizedError("邮箱或密码错误")

    if user.status != "active":
        await write_audit_entry(
            actor_email=email, action=audit.AUTH_LOGIN_FAILED, ip=ip,
            detail={"email": email, "reason": "disabled"},
        )
        raise UnauthorizedError("账号已被禁用")

    clear_login_failures(email)
    ctx = await load_user_ctx(session, str(user.id))
    ref_id = uuid.uuid4()
    result = await _issue_tokens(session, user, ctx, refresh_token_id=ref_id)
    await _store_refresh(
        session, user_id=str(user.id), refresh_jwt=result["refresh_token"],
        ref_id=ref_id, ip=ip, user_agent=user_agent,
    )
    await session.commit()

    await write_audit_entry(
        actor_id=str(user.id), actor_email=email, action=audit.AUTH_LOGIN,
        target_type="user", target_id=str(user.id), ip=ip,
        detail={"email": email}, session=session,
    )
    await session.commit()
    return {**result, "user": {"id": str(user.id), "email": user.email, "nickname": user.nickname}}


async def login_by_oa(
    session: AsyncSession,
    oa: str,
    ip: str = "",
    user_agent: str = "",
) -> dict:
    """OA 网关认证后按规范化 OA 幂等创建用户并签发本地 JWT。"""
    oa = normalize_oa(oa)
    try:
        oauth = await fetch_access_token(username=oa)
    except ValidationError:
        await write_audit_entry(
            actor_email="", action=audit.AUTH_LOGIN_FAILED, ip=ip,
            detail={"oa": oa}, session=session,
        )
        await session.commit()
        raise ValidationError(OA_LOGIN_FAILED_MESSAGE) from None

    # The lock and all user/role/token/audit writes share this transaction.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:oa, 0))"),
        {"oa": oa},
    )
    result = await session.execute(select(User).where(User.oa == oa))
    user = result.scalars().first()
    if user is None:
        user = User(
            email=f"{oa}@tcl.com",
            oa=oa,
            nickname=oa,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            status="active",
        )
        session.add(user)
        await session.flush()
        role = await _get_role_by_code(session, "user")
        if role is None:
            raise NotFoundError("预置角色 user 未初始化")
        session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.flush()
    elif user.status != "active":
        await write_audit_entry(
            actor_id=str(user.id), actor_email=user.email,
            action=audit.AUTH_LOGIN_FAILED, target_type="user", target_id=str(user.id),
            ip=ip, detail={"oa": oa, "reason": "disabled"}, session=session,
        )
        await session.commit()
        raise UnauthorizedError("账号已被禁用")

    ctx = await load_user_ctx(session, str(user.id))
    refresh_id = uuid.uuid4()
    local_tokens = await _issue_tokens(session, user, ctx, refresh_token_id=refresh_id)
    await _store_refresh(
        session, user_id=str(user.id), refresh_jwt=local_tokens["refresh_token"],
        ref_id=refresh_id, ip=ip, user_agent=user_agent,
    )
    await write_audit_entry(
        actor_id=str(user.id), actor_email=user.email, action=audit.AUTH_LOGIN,
        target_type="user", target_id=str(user.id), ip=ip,
        detail={"oa": oa}, session=session,
    )
    await session.commit()
    return {
        "oa": oa,
        "access_token": local_tokens["access_token"],
        "refresh_token": local_tokens["refresh_token"],
        "token_type": "Bearer",
        "expires_in": local_tokens["expires_in"],
        "oauth_access_token": oauth["access_token"],
        "oauth_token_type": oauth.get("token_type", "Bearer"),
        "oauth_expires_in": oauth.get("expires_in", 0),
    }


async def refresh_login(
    session: AsyncSession, refresh_token: str, *, ip: str = "", user_agent: str = ""
) -> dict:
    """refresh 轮换：旧行吊销 + replaced_by，签发新对。"""
    claims = decode_token(refresh_token)
    if claims.get("token_type") != "refresh":
        raise UnauthorizedError("令牌类型错误")
    token_hash = hash_refresh_token(refresh_token)

    res = await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    row = res.scalars().first()
    if row is None or row.revoked_at is not None:
        raise UnauthorizedError("刷新令牌已失效")

    import datetime as _dt

    expires = row.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=_dt.timezone.utc)  # 防御性：db 返回无 tz 时视为 UTC
    if expires is None or expires < _dt.datetime.now(_dt.timezone.utc):
        raise UnauthorizedError("刷新令牌已过期")

    user = await session.get(User, row.user_id)
    if user is None:
        raise UnauthorizedError("用户不存在")

    new_ref_id = uuid.uuid4()
    result = await _issue_tokens(session, user, await load_user_ctx(session, str(user.id)), refresh_token_id=new_ref_id)
    # 先插入新行并 flush（refresh_tokens.replaced_by 自引用 FK，PG 立即校验，须先存在目标行）
    await _store_refresh(
        session, user_id=str(user.id), refresh_jwt=result["refresh_token"],
        ref_id=new_ref_id, ip=ip, user_agent=user_agent,
    )
    await session.flush()
    # 旧行吊销
    row.revoked_at = _dt.datetime.now(_dt.timezone.utc)
    row.replaced_by = str(new_ref_id)
    await session.commit()
    return {**result, "user": {"id": str(user.id), "email": user.email, "nickname": user.nickname}}


async def logout_user(session: AsyncSession, refresh_token: str, actor_id: Optional[str] = None) -> None:
    """登出：吊销 refresh 行（X-Refresh-Token header）。"""
    try:
        decode_token(refresh_token)  # 校验有效性；无效 → return
    except Exception:
        return  # 无效 refresh 无需吊销
    token_hash = hash_refresh_token(refresh_token)
    res = await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    row = res.scalars().first()
    if row is not None and row.revoked_at is None:
        import datetime as _dt

        row.revoked_at = _dt.datetime.now(_dt.timezone.utc)
    await session.commit()
    if actor_id:
        await write_audit_entry(actor_id=actor_id, action=audit.AUTH_LOGOUT, target_type="session", session=session)
        await session.commit()


async def change_password(
    session: AsyncSession,
    *,
    user_id: str,
    old_password: str,
    new_password: str,
) -> None:
    """改密：校验旧密码 → 更新哈希。"""
    validate_password_policy(new_password)
    user = await session.get(User, user_id)
    if user is None or not verify_password(old_password, user.password_hash):
        raise UnauthorizedError("原密码错误")
    user.password_hash = hash_password(new_password)
    await session.commit()
    await write_audit_entry(actor_id=user_id, action=audit.AUTH_PASSWORD, target_type="user", target_id=user_id, session=session)
    await session.commit()


async def update_nickname(
    session: AsyncSession,
    *,
    user_id: str,
    nickname: str,
) -> User:
    """更新昵称（T28 / PRD P0-B8）：1~32 字符（H9，可中文），写审计 auth.profile_update。"""
    nickname = (nickname or "").strip()
    if not nickname:
        raise ValidationError("昵称不能为空")
    if len(nickname) > 32:
        raise ValidationError("昵称最长 32 字符")
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    user.nickname = nickname
    await session.commit()
    await write_audit_entry(
        actor_id=user_id, action=audit.AUTH_PROFILE_UPDATE,
        target_type="user", target_id=user_id, detail={"nickname": nickname}, session=session,
    )
    await session.commit()
    return user


async def write_audit_entry(*, actor_id=None, actor_email="", action, target_type=None, target_id=None, ip="", detail=None, session=None) -> None:  # noqa: D417
    """薄封装：复用 tracing.audit.write_audit；随业务事务(session)提交。

    session 传入时审计与业务同事务；None 时独立尽力写入。
    """
    await _write_audit(
        actor_id=actor_id, actor_email=actor_email, action=action,
        target_type=target_type, target_id=target_id, ip=ip, detail=detail,
        session=session,
    )
