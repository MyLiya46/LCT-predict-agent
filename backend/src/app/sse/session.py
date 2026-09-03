"""会话级事件流（Live Tail）回放 + 实时推送（T38）。

双端复用：用户端 /chat/conversations/{cid}/stream 与管理员端
/admin/conversations/{cid}/stream 共用本模块。

契约（T38 → T39/T42）：
- 连接后先回放最近 ≤200 条历史事件（按创建时间 + seq 升序，剔除内部 sse_opened），
  逐条发 `session.pack`（载荷 {event_type, payload, seq, turn_index, ts}）；
- 随后发 `session.meta`（{conversation_id, event_total, token_total}）；
- 再订阅 hub 实时推送，事件同样包装为 `session.pack`。
- payload 与 message_event 结构一致，不含 DS_TOKEN_*/api_key（本就不入 message_event）。

注意：回放查询在路由内（session 生命周期内）完成，实时订阅在生成器中进行。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, MessageEvent
from app.sse.events import (
    EVT_SESSION_META,
    EVT_SESSION_PACK,
    INTERNAL_TO_WIRE,
    SsePayload,
    sse_frame,
)
from app.sse.hub import Hub, SSEStreamer

REPLAY_LIMIT = 200  # 回放最近事件上限（【假设】200）


async def prepare_replay(
    session: AsyncSession, conversation_id: str
) -> tuple[list[str], str, int]:
    """在路由内完成回放，返回 (pack_frames, meta_frame, current_turn)。"""
    rows = (
        await session.execute(
            select(MessageEvent)
            .join(Message, Message.id == MessageEvent.message_id)
            .where(Message.conversation_id == conversation_id)
            .order_by(MessageEvent.created_at, MessageEvent.seq)
        )
    ).scalars().all()
    all_events = list(rows)

    visible = [e for e in all_events if e.type != "sse_opened"]
    replayed = visible[-REPLAY_LIMIT:]
    turn_by_trace: dict[str, int] = {}
    for e in replayed:
        if e.trace_id not in turn_by_trace:
            turn_by_trace[e.trace_id] = len(turn_by_trace) + 1

    frames: list[str] = []
    for e in replayed:
        wire = INTERNAL_TO_WIRE.get(e.type)
        if wire is None:
            continue
        ts = e.created_at.isoformat() if e.created_at else datetime.now(timezone.utc).isoformat()
        pack = SsePayload.session_pack(wire, e.payload or {}, e.seq, turn_by_trace[e.trace_id], ts)
        frames.append(sse_frame(EVT_SESSION_PACK, pack, e.seq))

    meta = SsePayload.session_meta(conversation_id, len(visible), _token_total(all_events))
    return frames, sse_frame(EVT_SESSION_META, meta, None), len(turn_by_trace)


def _token_total(events: list[MessageEvent]) -> int:
    """累计 token = 各 done 事件 usage 的 prompt+completion 之和。"""
    total = 0
    for e in events:
        if e.type == "done":
            u = (e.payload or {}).get("usage") or {}
            total += int(u.get("prompt_tokens", 0) or 0) + int(u.get("completion_tokens", 0) or 0)
    return total


async def live_stream(
    hub: Hub,
    cid: str,
    streamer: SSEStreamer,
    replay_frames: list[str],
    meta_frame: str,
    current_turn: int,
) -> AsyncIterator[str]:
    """回放 → meta → 实时订阅（包装为 session.pack）。"""
    try:
        for frame in replay_frames:
            yield frame
        yield meta_frame

        while not streamer.closed:
            got = await streamer.recv()
            if got is None:
                yield ": ping\n\n"
                continue
            event, data, seq = got
            if event == "message.created" or (
                event == "agent.process" and (data or {}).get("state") == "starting"
            ):
                current_turn += 1
            ts = datetime.now(timezone.utc).isoformat()
            pack = SsePayload.session_pack(event, data or {}, seq or 0, current_turn, ts)
            yield sse_frame(EVT_SESSION_PACK, pack, seq)
    finally:
        await hub.detach(cid, streamer)
