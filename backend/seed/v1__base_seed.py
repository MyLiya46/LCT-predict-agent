"""幂等种子 v1（T04 / tech_design §4.3 与 §3.11.5）。

初始化：user/admin 双角色、10 权限点、role_permission（user 5 / admin 10）、
默认场景 sales_query_predict、system_config 9 键、管理员账号（按 env）。

幂等：PG advisory lock + EXISTS 判断 + upsert（patched）。
用法：python -m seed.v1__base_seed
"""
from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.config import get_settings
from app.database import get_session_factory, get_database_url
from app.models import (
    Base, Conversation, DataSource, LlmProvider, Permission, Role, RolePermission,
    Scenario, SystemConfig, User, UserRole, Tool,
)

logger = logging.getLogger("seed")
SEED_ADVISORY_LOCK_ID = 99102026  # 固定常量（用于 PG advisory lock）

PERMISSIONS: list[tuple[str, str]] = [
    ("chat:read", "查看会话/消息"),
    ("chat:send", "发送消息"),
    ("chat:stop", "停止生成"),
    ("chat:delete", "删除会话"),
    ("trace:read", "查看自己的追溯链"),
    ("adm:user.manage", "用户管理"),
    ("adm:tool.manage", "工具/数据源管理"),
    ("adm:llm.manage", "LLM 配置"),
    ("adm:config.manage", "系统参数"),
    ("audit:read", "审计只读"),
]

USER_PERMS = ["chat:read", "chat:send", "chat:stop", "chat:delete", "trace:read"]
ADMIN_PERMS = USER_PERMS + ["adm:user.manage", "adm:tool.manage", "adm:llm.manage", "adm:config.manage", "audit:read"]

SYS_CONFIG_DEFAULTS: dict[str, object] = {
    "retention.conversation_days": 180,
    "retention.audit_days": 365,
    "auth.email_whitelist_suffixes": ["@corp.com"],
    "auth.login_fail_limit": 5,
    "sandbox.max_concurrent": 3,
    "sandbox.timeout_s": 30,
    "llm.default_provider_id": None,
    "llm.default_model": "",
    "conversation.user_max_messages": 48,
}

DEFAULT_SCENARIO = {
    "code": "sales_query_predict",
    "name": "销售查询预测",
    "system_prompt": (
        "你是销售数据分析助手。用户提出销售查询或预测需求时，请优先使用提供的工具获取数据：\n"
        "1. query_sales_data 用于查询历史销售数据（支持维度 region/product/channel，时间范围与筛选条件）；\n"
        "2. predict_sales 用于发起销售预测（基于历史数据）。\n"
        "回答需结构化：先给出结论，再附表格或简要明细；若工具失败请说明原因并尝试换一种表述。"
    ),
}

USER_FIELDS_LIMIT = 48


async def _advisory_lock(session: AsyncSession) -> None:
    """PG advisory lock（事务内，防并发种子）。"""
    await session.execute(text(f"SELECT pg_advisory_xact_lock({SEED_ADVISORY_LOCK_ID})"))


async def _llm_bootstrap(session: AsyncSession) -> None:
    """环境变量引导创建首个 LLM 供应商（幂等）。

    对齐 tech_design §7.3「LLM_API_KEYS（分号分隔）→ 首建 provider 用」：
    key 取分号分隔的首个，base_url / 默认模型来自 LLM_BASE_URL / LLM_DEFAULT_MODEL。
    任一条件不满足（未配置 / 已有任一 provider / 同名已存在）则跳过，可重复运行。
    """
    from app.config import get_settings
    from app.utils.security import encrypt_secret

    settings = get_settings()
    if not settings.has_llm_bootstrap:
        return
    existing = (await session.execute(select(LlmProvider).limit(1))).scalars().first()
    if existing is not None:
        return
    if (
        (await session.execute(select(LlmProvider).where(LlmProvider.name == "env-default")))
        .scalars()
        .first()
        is not None
    ):
        return
    provider = LlmProvider(
        name="env-default",
        vendor="openai_compat",
        base_url=settings.llm_base_url.strip().rstrip("/"),
        api_key_encrypted=encrypt_secret(settings.llm_api_keys_list[0]),
        models=([settings.llm_default_model.strip()] if settings.llm_default_model.strip() else []),
        default_model=settings.llm_default_model.strip(),
        status="healthy",
    )
    session.add(provider)
    logger.info("首建 LLM 供应商 env-default（base_url 来自 LLM_BASE_URL）")


async def run_seed(session: AsyncSession | None = None) -> None:
    """种子主流程（幂等）。"""
    if session is None:
        factory = get_session_factory()
        async with factory() as s:
            await run_seed(s)
        return

    async with session.begin():
        await _advisory_lock(session)

        # ---- 角色 ----
        roles = {}
        for code, name in (("user", "普通用户"), ("admin", "管理员")):
            exists = (await session.execute(select(Role).where(Role.code == code))).scalars().first()
            if exists is None:
                role = Role(code=code, name=name, builtin=True)
                session.add(role)
                await session.flush()
                roles[code] = role
            else:
                roles[code] = exists
        await session.flush()

        # ---- 权限点 ----
        perm_by_code: dict[str, Permission] = {}
        for code, name in PERMISSIONS:
            exists = (await session.execute(select(Permission).where(Permission.code == code))).scalars().first()
            if exists is None:
                p = Permission(code=code, name=name)
                session.add(p)
                await session.flush()
                perm_by_code[code] = p
            else:
                perm_by_code[code] = exists
        await session.flush()

        # ---- role_permission ----
        role_user = roles["user"]
        role_admin = roles["admin"]
        for code in USER_PERMS:
            rp = (
                await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role_user.id,
                        RolePermission.permission_id == perm_by_code[code].id,
                    )
                )
            ).scalars().first()
            if rp is None:
                session.add(RolePermission(role_id=role_user.id, permission_id=perm_by_code[code].id))
        for code in ADMIN_PERMS:
            rp = (
                await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role_admin.id,
                        RolePermission.permission_id == perm_by_code[code].id,
                    )
                )
            ).scalars().first()
            if rp is None:
                session.add(RolePermission(role_id=role_admin.id, permission_id=perm_by_code[code].id))
        await session.flush()

        # ---- system_config 初值 ----
        for key, value in SYS_CONFIG_DEFAULTS.items():
            exists = await session.get(SystemConfig, key)
            if exists is None:
                session.add(SystemConfig(key=key, value=value))

        # ---- 默认场景（假设 B：不预置工具注册，工具由 T14 后在管理端注册绑定）----
        scn = (
            await session.execute(select(Scenario).where(Scenario.code == DEFAULT_SCENARIO["code"]))
        ).scalars().first()
        if scn is None:
            session.add(
                Scenario(
                    code=DEFAULT_SCENARIO["code"],
                    name=DEFAULT_SCENARIO["name"],
                    model_ref={"provider_id": None, "model": ""},
                    system_prompt=DEFAULT_SCENARIO["system_prompt"],
                    enabled=True,
                )
            )

        # ---- 首个 LLM 供应商（tech_design §7.3：LLM_API_KEYS 首建 provider 用）----
        # 仅当 LLM_API_KEYS 与 LLM_BASE_URL 齐备时，以 env 引导建库；幂等（已存在同名/已有 provider 则跳过）。
        await _llm_bootstrap(session)

        # ---- 管理员初始化（P0-A4）----
        settings = get_settings()
        if settings.admin_initial_email and settings.admin_initial_password:
            admin_email = settings.admin_initial_email.strip().lower()
            exists = (await session.execute(select(User).where(User.email == admin_email))).scalars().first()
            if exists is None:
                admin_user = User(
                    email=admin_email,
                    password_hash=hash_password(settings.admin_initial_password),
                    nickname="管理员",
                    status="active",
                )
                session.add(admin_user)
                await session.flush()
                session.add(UserRole(user_id=admin_user.id, role_id=role_admin.id))
                logger.info("管理员账号已创建: %s (active)", admin_email)
            else:
                # 已存在：确保其角色为 admin 且激活
                ur = (
                    await session.execute(
                        select(UserRole).where(
                            UserRole.user_id == exists.id, UserRole.role_id == role_admin.id
                        )
                    )
                ).scalars().first()
                if ur is None:
                    session.add(UserRole(user_id=exists.id, role_id=role_admin.id))
                logger.info("管理员账号已存在: %s", admin_email)
        else:
            # 未设置 → 创建 disabled admin 占位并提示
            placeholder_email = "admin.disabled@corp.com"
            exists = (await session.execute(select(User).where(User.email == placeholder_email))).scalars().first()
            if exists is None:
                session.add(
                    User(
                        email=placeholder_email,
                        password_hash=hash_password("__placeholder__manual_enable__"),
                        nickname="管理员(待启用)",
                        status="disabled",
                    )
                )
                logger.info("未设置 ADMIN_INITIAL_*，创建 disabled 占位 admin（稍后由运维启用）")

        await session.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("seed v1 start (url_scheme=%s)", get_database_url().split(":")[0])
    asyncio.run(run_seed())
    logger.info("seed v1 done.")


if __name__ == "__main__":
    main()