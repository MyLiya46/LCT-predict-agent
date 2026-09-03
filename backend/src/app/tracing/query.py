"""追溯还原查询与 markdown 导出（T15 / tech_design §3.10）。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, MessageEvent
from app.tracing.trace import MESSAGE_CREATED
from app.utils.errors import NotFoundError


async def get_trace(
    session: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    owner_id: Optional[str] = None,
) -> dict[str, Any]:
    """还原 trace：{trace_id, status, events:[...]}。

    Args:
        owner_id: 传入时做 owner 归属校验（越权/不存在 → 404，不泄露存在性）。
    """
    msg = await session.get(Message, message_id)
    if msg is None or str(msg.conversation_id) != str(conversation_id):
        raise NotFoundError("消息不存在")
    if owner_id is not None:
        conv = await session.get(Conversation, str(conversation_id))
        if conv is None or str(conv.owner_id) != str(owner_id):
            raise NotFoundError("消息不存在")

    rows = (
        await session.execute(
            select(MessageEvent)
            .where(
                MessageEvent.trace_id == msg.trace_id,
                MessageEvent.message_id == message_id,
            )
            .order_by(MessageEvent.seq)
        )
    ).scalars().all()
    events = [
        {
            "seq": e.seq,
            "type": e.type,
            "payload": e.payload,
            "anomaly": e.anomaly,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]
    return {
        "trace_id": str(msg.trace_id),
        "status": msg.status,
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
        "events": events,
    }


def _payload_text(evt_type: str, payload: dict[str, Any]) -> str:
    text_parts: list[str] = []
    if evt_type == MESSAGE_CREATED:
        text_parts.append(f"用户消息: {payload.get('content', '')}")
    elif evt_type == "agent_process":
        state = payload.get("state")
        line = f"Agent 阶段: {state}"
        if payload.get("detail"):
            line += f" · {payload['detail']}"
        text_parts.append(line)
    elif evt_type == "tool_call":
        text_parts.append(
            f"工具调用: {payload.get('name')}(plan_index={payload.get('plan_index')})  入参: {payload.get('input')}"
        )
    elif evt_type == "tool_result":
        status = payload.get("status")
        text_parts.append(
            f"工具结果: {payload.get('name')} → {status} ({payload.get('duration_ms')}ms) 摘要: {payload.get('output')}"
        )
    elif evt_type == "tool_error":
        text_parts.append(
            f"工具失败: {payload.get('name')} · error_code={payload.get('error_code')} · "
            f"retried={payload.get('retried', 0)} · {payload.get('message')}"
        )
    elif evt_type == "done":
        text_parts.append(f"最终回复: {payload.get('final_text', '')}")
    return "; ".join(t for t in text_parts if t)


async def export_trace_markdown(
    session: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    owner_id: Optional[str] = None,
) -> str:
    """拼可读 markdown（PRD §12.2 trace/export）。"""
    trace = await get_trace(
        session, conversation_id=conversation_id, message_id=message_id, owner_id=owner_id
    )
    lines: list[str] = [f"# 追溯报告（message {message_id}）", ""]
    for evt in trace["events"]:
        lines.append(f"- [{evt['seq']} · {evt['type']}] {_payload_text(evt['type'], evt['payload'])}")
    if not trace["events"]:
        lines.append("_无事件记录_")
    return "\n".join(lines)