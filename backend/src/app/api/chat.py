"""用户端会话/消息/追溯路由（T17 / tech_design §3.3 & §5.3 SSE）。

SSE 建立：GET .../messages/{mid}/stream（bearer 经 fetch-stream 携带）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.auth.tokens import UserContext
from app.database import get_session
from app.domain.chat_service import (
    admin_list_messages,
    admin_list_sessions,
    create_conversation,
    delete_conversation,
    export_message_trace,
    get_conversation,
    get_message_trace,
    list_conversations,
    list_messages,
    pin_conversation,
    rename_conversation,
    send_message,
    stop_message,
)
from app.models import Message
from app.sse.hub import Hub, SSEStreamer
from app.tracing.trace import SSE_OPENED, append_event
from app.utils.errors import NotFoundError, to_uni

router = APIRouter(prefix="/chat", tags=["chat"])


class ConversationIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)


class RenameIn(BaseModel):
    title: str = Field(..., max_length=255)


class PinIn(BaseModel):
    pinned: bool


class MessageIn(BaseModel):
    content: str = Field(..., max_length=65536)


# ------------------------------------------------------------------
# 会话
# ------------------------------------------------------------------
@router.get("/conversations")
async def conversations(
    cursor: Optional[str] = None, limit: int = 20,
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    data = await list_conversations(session, ctx.id, cursor=cursor, limit=min(limit, 100))
    return to_uni(data)


@router.post("/conversations")
async def create_conv(
    body: ConversationIn,
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    conv = await create_conversation(session, ctx.id, title=body.title or "新会话")
    return to_uni({"id": str(conv.id), "title": conv.title, "created_at": conv.created_at.isoformat() if conv.created_at else None})


@router.get("/conversations/{cid}")
async def conversation_detail(
    cid: str, ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    conv = await get_conversation(session, cid, ctx.id)
    return to_uni(
        {
            "id": str(conv.id), "title": conv.title, "status": conv.status,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
        }
    )


@router.patch("/conversations/{cid}")
async def rename_conv(
    cid: str, body: RenameIn, ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    conv = await rename_conversation(session, cid, ctx.id, body.title)
    return to_uni({"id": str(conv.id), "title": conv.title})


@router.patch("/conversations/{cid}/pin")
async def pin_conv(
    cid: str, body: PinIn, ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    conv = await pin_conversation(session, cid, ctx.id, body.pinned)
    return to_uni(
        {
            "id": str(conv.id), "pinned": conv.pinned,
            "pinned_at": conv.pinned_at.isoformat() if conv.pinned_at else None,
        }
    )


@router.delete("/conversations/{cid}")
async def delete_conv(
    cid: str, ctx: UserContext = Depends(require_perm("chat:delete")),
    session: AsyncSession = Depends(get_session),
):
    await delete_conversation(session, cid, ctx.id)
    return to_uni({"ok": True})


# ------------------------------------------------------------------
# 消息
# ------------------------------------------------------------------
@router.get("/conversations/{cid}/messages")
async def messages_list(
    cid: str, cursor: Optional[str] = None, limit: int = 20,
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    data = await list_messages(session, cid, ctx.id, cursor=cursor, limit=min(limit, 100))
    return to_uni(data)


@router.post("/conversations/{cid}/messages")
async def messages_send(
    cid: str, body: MessageIn,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ctx: UserContext = Depends(require_perm("chat:send")),
    session: AsyncSession = Depends(get_session),
):
    data = await send_message(
        session, conversation_id=cid, owner_id=ctx.id,
        content=body.content, idem_key=idempotency_key,
    )
    return to_uni(data)


@router.post("/conversations/{cid}/messages/{mid}/stop")
async def messages_stop(
    cid: str, mid: str, ctx: UserContext = Depends(require_perm("chat:stop")),
    session: AsyncSession = Depends(get_session),
):
    await stop_message(session, cid, mid, ctx.id)
    return to_uni({"ok": True})


@router.get("/conversations/{cid}/messages/{mid}/stream")
async def messages_stream(
    request: Request, cid: str, mid: str,
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    """SSE 流（fetch-stream 带 Bearer；TTL 心跳；done/error 后 detach）。"""
    msg = await session.get(Message, mid)
    await get_conversation(session, cid, ctx.id)  # owner 校验（存在且未删除）
    if msg is None or str(msg.conversation_id) != cid:
        raise NotFoundError("消息不存在")

    from app.domain.chat_service import _get_hub

    hub: Hub = _get_hub()
    streamer = SSEStreamer(cid)
    await hub.attach(cid, streamer)
    if msg.trace_id:
        await append_event(
            session, trace_id=str(msg.trace_id), message_id=mid,
            type=SSE_OPENED, payload={},
        )
    await session.commit()

    async def gen():
        try:
            async for frame in streamer.iter_frames():
                yield frame
        finally:
            await hub.detach(cid, streamer)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations/{cid}/stream")
async def conversation_stream(
    cid: str, ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    """会话级事件流 SSE（Live Tail，用户端 owner 语义，越权/不存在 → 404，不写审计）。"""
    await get_conversation(session, cid, ctx.id)  # owner 校验（404 不泄露存在性）

    from app.domain.chat_service import _get_hub
    from app.sse.session import live_stream, prepare_replay

    hub: Hub = _get_hub()
    streamer = SSEStreamer(cid)
    await hub.attach(cid, streamer)
    replay_frames, meta_frame, current_turn = await prepare_replay(session, cid)

    return StreamingResponse(
        live_stream(hub, cid, streamer, replay_frames, meta_frame, current_turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------
# 追溯
# ------------------------------------------------------------------
@router.get("/conversations/{cid}/messages/{mid}/trace")
async def message_trace(
    cid: str, mid: str, ctx: UserContext = Depends(require_perm("trace:read")),
    session: AsyncSession = Depends(get_session),
):
    data = await get_message_trace(session, cid, mid, ctx.id)
    return to_uni(data)


@router.get("/conversations/{cid}/messages/{mid}/trace/export")
async def message_trace_export(
    cid: str, mid: str, ctx: UserContext = Depends(require_perm("trace:read")),
    session: AsyncSession = Depends(get_session),
):
    md = await export_message_trace(session, cid, mid, ctx.id)
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="trace-{mid}.md"'},
    )


# ------------------------------------------------------------------
# 管理端只读（T20 在 /admin 下复用函数，实现在 admin/audits.py）
# ------------------------------------------------------------------
async def _admin_sessions(session: AsyncSession, **kwargs):
    return await admin_list_sessions(session, **kwargs)


async def _admin_messages(session: AsyncSession, **kwargs):
    return await admin_list_messages(session, **kwargs)
