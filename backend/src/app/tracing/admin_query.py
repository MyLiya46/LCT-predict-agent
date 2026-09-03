"""追溯管理查询 + 保留清理（T15 / 供 T19/T20 复用）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Conversation, Message, MessageEvent


async def query_traces(
    session: AsyncSession,
    *,
    trace_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    error_code: Optional[str] = None,
    actor_email: Optional[str] = None,
    time_from: Optional[datetime] = None,
    time_to: Optional[datetime] = None,
    cursor: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """管理端追溯检索（JSONB GIN 过滤）。"""
    stmt = (
        select(MessageEvent, Message)
        .join(Message, Message.id == MessageEvent.message_id)
        .order_by(MessageEvent.created_at.desc())
        .limit(limit)
    )
    if trace_id:
        stmt = stmt.where(MessageEvent.trace_id == trace_id)
    if tool_name:
        stmt = stmt.where(MessageEvent.payload["name"].astext == tool_name)
    if error_code and error_code.upper() not in ("", "ANY"):
        stmt = stmt.where(MessageEvent.payload["error_code"].astext == error_code.upper())
    if actor_email:
        from app.models import Conversation, User

        stmt = stmt.join(Conversation, Conversation.id == Message.conversation_id)
        stmt = stmt.join(User, User.id == Conversation.owner_id)
        stmt = stmt.where(User.email == actor_email)
    if time_from:
        stmt = stmt.where(MessageEvent.created_at >= time_from)
    if time_to:
        stmt = stmt.where(MessageEvent.created_at <= time_to)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "trace_id": str(e.trace_id),
            "message_id": str(e.message_id),
            "seq": e.seq,
            "type": e.type,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e, _m in rows
    ]


async def purge_expired(
    session: AsyncSession,
    *,
    conversation_days: int,
    audit_days: int,
    soft_delete_days: int = 15,
) -> dict[str, int]:
    """保留清理（T15 §3.10 + T19 接线）。

    1. 删除超期不活跃会话（级联 message/message_event/checkpoint 物理删除）
    2. 删除超期审计
    3. 软删>15d 的会话物理清理
    删除动作写审计 system.retention（由调用方或本函数写，本函数返回计数）。
    """
    now = datetime.now(timezone.utc)
    cutoff_conv = now - timedelta(days=conversation_days)
    cutoff_audit = now - timedelta(days=audit_days)
    cutoff_soft = now - timedelta(days=soft_delete_days)

    # 1) 不活跃会话（含 archived/deleted 之外的 active，按 updated_at < cutoff 且无新消息）
    stmt = (
        select(Conversation.id)
        .where(Conversation.updated_at < cutoff_conv)
        .where(Conversation.status != "deleted")
    )
    stale_ids = [str(r) for r in (await session.execute(stmt)).scalars().all()]
    for cid in stale_ids:
        msg_ids = [
            str(r)
            for r in (
                await session.execute(
                    select(Message.id).where(Message.conversation_id == cid)
                )
            ).scalars().all()
        ]
        if msg_ids:
            await session.execute(
                delete(MessageEvent).where(MessageEvent.message_id.in_(msg_ids))
            )
        await session.execute(delete(Message).where(Message.conversation_id == cid))
        await session.execute(delete(Conversation).where(Conversation.id == cid))

    # 3) 软删超期会话
    soft_ids = [
        str(r)
        for r in (
            await session.execute(
                select(Conversation.id).where(Conversation.deleted_at.is_not(None)).where(
                    Conversation.deleted_at < cutoff_soft
                )
            )
        ).scalars().all()
    ]
    for cid in soft_ids:
        msg_ids = [
            str(r)
            for r in (
                await session.execute(
                    select(Message.id).where(Message.conversation_id == cid)
                )
            ).scalars().all()
        ]
        if msg_ids:
            await session.execute(
                delete(MessageEvent).where(MessageEvent.message_id.in_(msg_ids))
            )
        await session.execute(delete(Message).where(Message.conversation_id == cid))
        await session.execute(delete(Conversation).where(Conversation.id == cid))

    # 2) 审计清理
    aud = await session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff_audit))
    audit_deleted = aud.rowcount or 0

    await session.commit()
    return {
        "conversations_deleted": len(stale_ids) + len(soft_ids),
        "audit_deleted": audit_deleted,
    }