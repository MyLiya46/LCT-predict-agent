"""审计写入基座（T05）。

write_audit 为 async 版本；write_audit_sync 供异常处理器（同步上下文）使用。
审计写入幂等、不抛业务异常（审计失败仅记日志，不断链）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import AuditLog

logger = logging.getLogger("app.audit")

# ------------------------------------------------------------------
# action 常量（tech_design §6.5 覆盖项 + §3.11 各域）
# ------------------------------------------------------------------
AUTH_REGISTER = "auth.register"
AUTH_LOGIN = "auth.login"
AUTH_LOGIN_FAILED = "auth.login_failed"
AUTH_LOGOUT = "auth.logout"
AUTH_PASSWORD = "auth.password"
AUTH_PROFILE_UPDATE = "auth.profile_update"
AUTHZ_DENIED = "authz.denied"
AUDIT_VIEW = "audit.view"
CHAT_CONVERSATION_DELETE = "chat.conversation.delete"
CHAT_CONVERSATION_UPDATE = "chat.conversation.update"
ADM_USER_CREATE = "adm.user.create"
ADM_USER_UPDATE = "adm.user.update"
ADM_USER_RESET_PASSWORD = "adm.user.reset_password"
ADM_TOOL_CREATE = "adm.tool.create"
ADM_TOOL_UPDATE = "adm.tool.update"
ADM_TOOL_DELETE = "adm.tool.delete"
ADM_TOOL_TEST = "adm.tool.test"
ADM_DATASOURCE_CREATE = "adm.datasource.create"
ADM_DATASOURCE_UPDATE = "adm.datasource.update"
ADM_DATASOURCE_TEST = "adm.datasource.test"
ADM_LLM_CREATE = "adm.llm.create"
ADM_LLM_UPDATE = "adm.llm.update"
ADM_LLM_HEALTH = "adm.llm.health"
ADM_CONFIG_UPDATE = "adm.config.update"
ADM_SCENARIO_UPDATE = "adm.scenario.update"
SYSTEM_RETENTION = "system.retention"
SYSTEM_LLM_PROBE = "system.llm.probe"


async def write_audit(
    *,
    actor_id: Optional[str] = None,
    actor_email: str = "",
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    ip: str = "",
    detail: Optional[dict[str, Any]] = None,
    session: Optional[AsyncSession] = None,
) -> None:
    """写入 audit_logs（失败不抛业务异常）。

    Args:
        session: 若在业务事务内则传给它（随事务提交）；否则自动开独立 session
                 尽力写入（审计不参与业务回滚，保持留痕可靠）。
    """
    detail = detail or {}
    try:
        if session is not None:
            session.add(
                AuditLog(
                    actor_id=actor_id,
                    actor_email=actor_email,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    ip=ip,
                    detail=detail,
                )
            )
            return
        factory = get_session_factory()
        async with factory() as s:
            s.add(
                AuditLog(
                    actor_id=actor_id,
                    actor_email=actor_email,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    ip=ip,
                    detail=detail,
                )
            )
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.exception("write_audit failed action=%s", action)


def write_audit_sync(
    *,
    actor_id: Optional[str] = None,
    actor_email: str = "",
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    ip: str = "",
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """事件循环内尽力写审计（中间件/异常处理器使用）。

    - 存在 running loop：fire-and-forget task（审计尽力投递，不阻塞业务）
    - 无 running loop：用临时 loop run_until_complete
    """
    import asyncio

    async def _do() -> None:
        await write_audit(
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            detail=detail,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    try:
        if loop is not None:
            asyncio.ensure_future(_do())
        else:
            asyncio.new_event_loop().run_until_complete(_do())
    except Exception:  # noqa: BLE001, S110
        logger.exception("write_audit_sync failed action=%s", action)
