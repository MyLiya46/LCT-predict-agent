"""system_config 表读取服务（tech_design §3.11.5 / T06 起复用）。

进程内 TTL 缓存 + invalidate 由 config.invalidate_config_key 兜底（T20 PATCH）。
默认值与 §3.11.5 表格一致。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemConfig

DEFAULTS: dict[str, Any] = {
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

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_S = 30.0


def _cached(key: str) -> tuple[bool, Any]:
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return True, hit[1]
    return False, None


def invalidate_sys_config(key: str) -> None:
    _CACHE.pop(key, None)


async def get_sys_config(session: AsyncSession, key: str, default: Any = None) -> Any:
    """读 system_config 键值（带缓存/默认值）。"""
    hit, val = _cached(key)
    if hit:
        return val
    row = await session.get(SystemConfig, key)
    value = row.value if row is not None else (default if default is not None else DEFAULTS.get(key))
    _CACHE[key] = (time.monotonic(), value)
    return value


async def set_sys_config(
    session: AsyncSession, key: str, value: Any, updated_by: Optional[str] = None
) -> None:
    """写 system_config（upsert）+ 失效本地缓存。"""
    row = await session.get(SystemConfig, key)
    if row is None:
        row = SystemConfig(key=key, value=value, updated_by=updated_by)
        session.add(row)
    else:
        row.value = value
        row.updated_by = updated_by
    invalidate_sys_config(key)

    from app.config import invalidate_config_key

    invalidate_config_key(key)


async def list_sys_config(session: AsyncSession) -> dict[str, Any]:
    """返回全部白名单系统参数（T20 用）。"""
    from sqlalchemy import select

    rows = (await session.execute(select(SystemConfig))).scalars().all()
    out: dict[str, Any] = dict(DEFAULTS)
    for row in rows:
        if row.key in DEFAULTS:
            out[row.key] = row.value
    return out