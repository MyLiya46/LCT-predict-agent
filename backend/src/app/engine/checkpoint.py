"""Checkpoint 管理（T16 / tech_design §3.4）。

每轮 LLM 前保存 checkpoint（追加为主，覆盖式取最新 seq）。恢复=以快照重发新 flow。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Checkpoint


async def save_checkpoint(
    session: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    trace_id: Optional[str],
    messages_snapshot: list[dict[str, Any]],
    engine_cursor: int,
    scenario_id: Optional[str],
    provider_id: Optional[str],
) -> Checkpoint:
    """每轮 LLM 前保存 checkpoint（UNIQUE(message_id, seq)，seq=MAX+1）。"""
    max_seq = await session.execute(
        select(func.max(Checkpoint.seq)).where(Checkpoint.message_id == message_id)
    )
    seq = (max_seq.scalar() or 0) + 1
    ckpt = Checkpoint(
        conversation_id=conversation_id,
        message_id=message_id,
        seq=seq,
        state={
            "messages_snapshot": messages_snapshot,
            "engine_cursor": engine_cursor,
            "scenario_id": scenario_id,
            "provider_id": provider_id,
        },
        trace_id=trace_id,
    )
    session.add(ckpt)
    return ckpt


async def latest_checkpoint(session: AsyncSession, message_id: str) -> Optional[Checkpoint]:
    """取某消息最新 checkpoint。"""
    row = (
        await session.execute(
            select(Checkpoint)
            .where(Checkpoint.message_id == message_id)
            .order_by(Checkpoint.seq.desc())
            .limit(1)
        )
    ).scalars().first()
    return row