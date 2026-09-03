"""全链路追溯：事件链追加（T15 / DEV-6 行式模型 / tech_design 附录 C）。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageEvent

# 内部事件字典（对齐 tech_design 附录 C）
MESSAGE_CREATED = "message_created"
AGENT_PROCESS = "agent_process"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
SSE_OPENED = "sse_opened"
DONE = "done"


async def append_event(
    session: AsyncSession,
    *,
    trace_id: str,
    message_id: str,
    type: str,  # noqa: A002
    payload: Optional[dict[str, Any]] = None,
    anomaly: bool = False,
) -> int:
    """追加事件：seq = MAX(seq)+1（同一 trace）；同 txn 随业务提交。返回 seq。"""
    payload = payload or {}
    max_seq = await session.execute(
        select(func.max(MessageEvent.seq)).where(MessageEvent.trace_id == trace_id)
    )
    next_seq = (max_seq.scalar() or 0) + 1
    session.add(
        MessageEvent(
            trace_id=trace_id,
            message_id=message_id,
            seq=next_seq,
            type=type,
            payload=payload,
            anomaly=anomaly,
        )
    )
    return next_seq