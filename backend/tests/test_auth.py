"""T06 认证模块单测（service 层，PostgreSQL）：注册/白名单/登录/轮换/吊销/锁定。"""

import pytest
from sqlalchemy import select

from app.auth.lockout import assert_not_locked, clear_login_failures, record_login_failure
from app.domain.auth_service import (
    change_password,
    login_user,
    logout_user,
    refresh_login,
    register_user,
)
from app.models import User
from app.utils.errors import RateLimitError, UnauthorizedError, ValidationError


@pytest.mark.asyncio
async def test_register_whitelist(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        # 白名单外
        with pytest.raises(ValidationError):
            await register_user(s, email="x@gmail.com", password="Passw0rd123")
        # 白名单内成功
        u = await register_user(s, email="alice@corp.com", password="Passw0rd123", nickname="A")
        assert u.email == "alice@corp.com"
        # 重复注册 → 冲突
        from app.utils.errors import ConflictError

        with pytest.raises(ConflictError):
            await register_user(s, email="alice@corp.com", password="Passw0rd123")


@pytest.mark.asyncio
async def test_login_refresh_logout_rotate(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        await register_user(s, email="bob@corp.com", password="Passw0rd123", nickname="B")
    async with factory() as s:
        data = await login_user(s, email="bob@corp.com", password="Passw0rd123")
        assert "access_token" in data and "refresh_token" in data
        rid = data["refresh_token"]

        # 轮换：旧 refresh 立即失效
        data2 = await refresh_login(s, rid)
        assert data2["access_token"]
        with pytest.raises(UnauthorizedError):
            await refresh_login(s, rid)  # 旧已吊销

    async with factory() as s:
        # logout 吊销
        data3 = await login_user(s, email="bob@corp.com", password="Passw0rd123")
        await logout_user(s, data3["refresh_token"], actor_id="0")
        with pytest.raises(UnauthorizedError):
            await refresh_login(s, data3["refresh_token"])


@pytest.mark.asyncio
async def test_login_failed_and_change_password(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        await register_user(s, email="carol@corp.com", password="Passw0rd123", nickname="C")
    async with factory() as s:
        # 错误密码
        with pytest.raises(UnauthorizedError):
            await login_user(s, email="carol@corp.com", password="WrongPass123")
        # 改密（正确旧密码）
        user = (await s.execute(select(User).where(User.email == "carol@corp.com"))).scalars().first()
        await change_password(s, user_id=str(user.id), old_password="Passw0rd123", new_password="NewPassw0rd456")
        with pytest.raises(UnauthorizedError):
            await login_user(s, email="carol@corp.com", password="Passw0rd123")
        await login_user(s, email="carol@corp.com", password="NewPassw0rd456")  # 新密码成功


def test_lockout_logic():
    clear_login_failures("lock@corp.com")
    for _ in range(5):
        record_login_failure("lock@corp.com")
    with pytest.raises(RateLimitError):
        assert_not_locked("lock@corp.com", 5)


# ------------------------------------------------------------------
# T27：错误提示可读（口令政策 → 400_VALIDATION + 人话 message，不落 500）
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_register_weak_password_is_validation_error(db_session_factory):
    """弱密码注册：PasswordPolicyError（现继承 ValidationError）→ 400 语义 + 可读 message。"""
    from app.domain.auth_service import PasswordPolicyError

    factory = db_session_factory
    async with factory() as s:
        with pytest.raises(PasswordPolicyError) as ei:
            await register_user(s, email="eve@corp.com", password="abcdefghij")  # 无大写/数字
        assert "大小写" in ei.value.message
        assert ei.value.code == "400_VALIDATION"
        with pytest.raises(PasswordPolicyError) as ei:
            await register_user(s, email="eve@corp.com", password="Ab1")  # 过短
        assert "长度" in ei.value.message


@pytest.mark.asyncio
async def test_login_failure_message_readable(db_session_factory):
    """登录失败 message 为可读文案（非技术堆栈），错误码仅作技术标识。"""
    factory = db_session_factory
    async with factory() as s:
        with pytest.raises(UnauthorizedError) as ei:
            await login_user(s, email="nobody@corp.com", password="WrongPass123")
        assert ei.value.message == "邮箱或密码错误"
        assert ei.value.code == "401_UNAUTHORIZED"


def test_register_in_password_accepts_short_then_service_validates():
    """联调修复：RegisterIn 不设 pydantic min_length —— 口令政策统一在 service 层
    返回 400_VALIDATION + 中文文案，避免 422 英文技术文案（T27 三层方案 b）。"""
    from app.api.auth import RegisterIn

    m = RegisterIn(email="a@corp.com", password="abc123")
    assert m.password == "abc123"


@pytest.mark.asyncio
async def test_me_returns_live_nickname(db_session_factory):
    """联调修复：/auth/me 返回库中实时昵称（JWT claims 中的 nickname 是签发快照）。"""
    from app.api.auth import me as me_route
    from app.auth.tokens import UserContext
    from app.domain.auth_service import update_nickname

    factory = db_session_factory
    async with factory() as s:
        u = await register_user(s, email="me@corp.com", password="Passw0rd123", nickname="stale_nick")
        uid = str(u.id)
        await update_nickname(s, user_id=uid, nickname="live_nick")
    async with factory() as s:
        ctx = UserContext(user_id=uid, email="me@corp.com", nickname="stale_nick")  # 模拟 JWT 快照
        resp = await me_route(ctx=ctx, session=s)
        assert resp["data"]["nickname"] == "live_nick"


# ------------------------------------------------------------------
# T28：个人设置-基础信息（昵称更新 + 审计；改密复用既有 change_password）
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_nickname(db_session_factory):
    """PATCH /auth/me 语义：昵称更新成功 + 审计 auth.profile_update；空/超长 → 400。"""
    from app.domain.auth_service import update_nickname

    factory = db_session_factory
    async with factory() as s:
        u = await register_user(s, email="nick@corp.com", password="Passw0rd123", nickname="旧名")
        uid = str(u.id)
    async with factory() as s:
        u2 = await update_nickname(s, user_id=uid, nickname="新名中文")
        assert u2.nickname == "新名中文"
        with pytest.raises(ValidationError):
            await update_nickname(s, user_id=uid, nickname="   ")
        with pytest.raises(ValidationError):
            await update_nickname(s, user_id=uid, nickname="长" * 33)
    async with factory() as s:
        from app.models import AuditLog

        rows = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "auth.profile_update"))).scalars().all()
        )
        assert any(str(r.target_id) == uid for r in rows)
