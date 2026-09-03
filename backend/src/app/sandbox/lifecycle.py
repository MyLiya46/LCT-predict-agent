"""沙箱实例生命周期记录（T13 / tech_design §3.7 + 附录 B 还原）。

daemon 不写库；由 api 侧 record_start / record_finish 落 sandbox_instances。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SandboxInstance


async def record_start(
    session: AsyncSession,
    *,
    tool_id: str,
    trace_id: Optional[str],
    message_id: Optional[str],
    request_id: str,
    image: Optional[str] = None,
) -> SandboxInstance:
    inst = SandboxInstance(
        tool_id=tool_id,
        trace_id=trace_id,
        message_id=message_id,
        request_id=request_id,
        status="created",
        image=image,
    )
    session.add(inst)
    await session.flush()
    return inst


async def record_finish(
    session: AsyncSession,
    instance: SandboxInstance,
    *,
    status: str,  # completed | timeout | error | aborted
    container_id: Optional[str] = None,
    reused_warm: bool = False,
    exit_code: Optional[int] = None,
) -> None:
    instance.status = status
    if container_id is not None:
        instance.container_id = container_id
    instance.reused_warm = reused_warm
    instance.exit_code = exit_code
    instance.terminated_at = datetime.now(timezone.utc)