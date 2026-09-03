"""沙箱全局限流接入点（T13 / tech_design §3.4 沙箱拉起失败 → 全局限流 degraded）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_service import get_sys_config, set_sys_config

GLOBAL_LIMIT_DEGRADED = "degraded"


async def check_global_limit(session: AsyncSession) -> bool:
    """是否处于全局降级（degraded）——true 表示当前应拒绝新沙箱任务。"""
    state = await get_sys_config(session, "sandbox.global_limit_state", "normal")
    return state == GLOBAL_LIMIT_DEGRADED


async def set_global_degraded(session: AsyncSession) -> None:
    """置 degraded（沙箱拉起失败时由引擎调用）。"""
    await set_sys_config(session, "sandbox.global_limit_state", GLOBAL_LIMIT_DEGRADED)
    await session.commit()


async def set_global_normal(session: AsyncSession) -> None:
    await set_sys_config(session, "sandbox.global_limit_state", "normal")
    await session.commit()