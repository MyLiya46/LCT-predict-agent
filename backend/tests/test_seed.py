"""T04 种子幂等性单测（PostgreSQL）。

断言：双角色、10 权限点、role_permission（user 5 + admin 10=15）、
默认场景、system_config 9 键、管理员初始化。
"""

import pytest

from app.config import get_settings
from seed.v1__base_seed import (
    ADMIN_PERMS,
    PERMISSIONS,
    SYS_CONFIG_DEFAULTS,
    USER_PERMS,
    run_seed,
)
from sqlalchemy import func, select

from app.models import Permission, Role, Scenario, SystemConfig, User, UserRole


@pytest.mark.asyncio
async def test_seed_idempotent_and_counts(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        await run_seed(s)  # 二次执行验证幂等
        await run_seed(s)

        roles = (await s.execute(select(func.count()).select_from(Role))).scalar()
        perms = (await s.execute(select(func.count()).select_from(Permission))).scalar()
        rp = (await s.execute(select(func.count()).select_from(__import__("app.models", fromlist=["RolePermission"]).RolePermission))).scalar()
        assert roles == 2, f"角色应 2，实际 {roles}"  # user + admin
        assert perms == 10
        assert rp == len(USER_PERMS) + len(ADMIN_PERMS), f"role_permission 应 {len(USER_PERMS)+len(ADMIN_PERMS)}，实际 {rp}"

        # 场景
        scn = (await s.execute(select(Scenario).where(Scenario.code == "sales_query_predict"))).scalars().first()
        assert scn is not None and scn.enabled

        # system_config 9 键
        cfg_keys = (await s.execute(select(SystemConfig.key))).scalars().all()
        assert set(cfg_keys) == set(SYS_CONFIG_DEFAULTS.keys())

        # 管理员
        settings = get_settings()
        if settings.admin_initial_email:
            admin = (await s.execute(select(User).where(User.email == settings.admin_initial_email))).scalars().first()
            assert admin is not None
            ur = (await s.execute(select(UserRole).where(UserRole.user_id == admin.id))).scalars().all()
            assert len(ur) == 1


@pytest.mark.asyncio
async def test_seed_roles_perms_codes(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        role_codes = (await s.execute(select(Role.code))).scalars().all()
        assert set(role_codes) == {"user", "admin"}
        perm_codes = (await s.execute(select(Permission.code))).scalars().all()
        assert set(perm_codes) == {c for c, _ in PERMISSIONS}, "权限点字典与 §3.2 不一致"