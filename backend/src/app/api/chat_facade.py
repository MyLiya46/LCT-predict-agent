"""Frontend workbench chat façade.

This module intentionally sits beside (rather than inside) the native
``/api/v1/chat`` router.  Native trace/live-tail consumers keep their original
``{code, message, data}`` protocol and event names.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.auth.tokens import UserContext
from app.config import get_settings
from app.database import get_session, get_session_factory
from app.domain.chat_service import (
    delete_conversation,
    get_conversation,
    list_conversations,
    pin_conversation,
    rename_conversation,
)
from app.models import Conversation, FcstForecastResult, Message
from app.services.chat_bridge import collect_turn, start_turn
from app.sse.events import sse_frame
from app.utils.errors import ValidationError

router = APIRouter(tags=["chat-facade"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=65536)
    session_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    oa: str | None = None
    access_token: str | None = None

    @model_validator(mode="after")
    def non_blank_message(self) -> "ChatRequest":
        if not self.message.strip():
            raise ValueError("message 不能为空")
        return self


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    pinned: bool | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "SessionPatch":
        if self.title is None and self.pinned is None:
            raise ValueError("至少提供 title 或 pinned")
        if self.title is not None and not self.title.strip():
            raise ValueError("title 不能为空")
        return self


def _summary(conv: Conversation) -> dict[str, Any]:
    return {
        "id": str(conv.id),
        "title": conv.title,
        "status": conv.status,
        "pinned": bool(conv.pinned),
        "pinned_at": conv.pinned_at.isoformat() if conv.pinned_at else None,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


@router.get("/api/sessions")
async def sessions(ctx: UserContext = Depends(require_perm("chat:read")), session: AsyncSession = Depends(get_session)):
    data = await list_conversations(session, ctx.id, limit=100)
    return data.get("items", [])


@router.patch("/api/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: SessionPatch,
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    conv = await get_conversation(session, session_id, ctx.id)
    if body.title is not None:
        conv = await rename_conversation(session, session_id, ctx.id, body.title.strip())
    if body.pinned is not None:
        if body.pinned and not conv.pinned:
            count = await session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.owner_id == ctx.id,
                    Conversation.pinned.is_(True),
                    Conversation.status != "deleted",
                )
            )
            if int(count or 0) >= 5:
                raise ValidationError("最多置顶 5 个会话")
        conv = await pin_conversation(session, session_id, ctx.id, body.pinned)
    return _summary(conv)


@router.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    ctx: UserContext = Depends(require_perm("chat:delete")),
    session: AsyncSession = Depends(get_session),
):
    await delete_conversation(session, session_id, ctx.id)
    return {"ok": True}


@router.get("/api/sessions/{session_id}")
async def session_detail(
    session_id: str,
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    conv = await get_conversation(session, session_id, ctx.id)
    rows = (
        await session.execute(
            select(Message)
            .where(
                Message.conversation_id == str(conv.id),
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    return {
        "id": str(conv.id),
        "title": conv.title,
        "messages": [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content,
                "result_envelope": msg.result_envelope if msg.role == "assistant" else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in rows
        ],
    }


async def _run_turn(session: AsyncSession, ctx: UserContext, body: ChatRequest, idem: str | None):
    handle = await start_turn(session, ctx, body, idempotency_key=idem)
    return await collect_turn(handle)


async def _live_turn_events(
    handle: Any,
    *,
    collector: Callable[..., Awaitable[dict[str, Any]]] = collect_turn,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Relay status callbacks while the turn is still running.

    The façade must keep the database session alive for ``collector`` while
    also yielding status frames to the browser.  A queue separates those two
    consumers without buffering the whole turn before the first SSE frame.
    """

    statuses: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_status(status: dict[str, Any]) -> None:
        await statuses.put(status)

    collect_task = asyncio.create_task(collector(handle, on_status=on_status))
    status_task: asyncio.Task[dict[str, Any]] | None = asyncio.create_task(statuses.get())
    try:
        while True:
            assert status_task is not None
            done, _ = await asyncio.wait(
                {collect_task, status_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if status_task in done:
                status = status_task.result()
                yield ("delta" if status.get("delta") is not None else "status"), status
                status_task = asyncio.create_task(statuses.get())
            if collect_task in done:
                result = collect_task.result()
                while not statuses.empty():
                    status = statuses.get_nowait()
                    yield ("delta" if status.get("delta") is not None else "status"), status
                yield "result", result
                return
    finally:
        if status_task is not None and not status_task.done():
            status_task.cancel()
        if not collect_task.done():
            collect_task.cancel()
        await asyncio.gather(
            *(task for task in (collect_task, status_task) if task is not None),
            return_exceptions=True,
        )


@router.post("/api/chat")
async def chat(
    body: ChatRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ctx: UserContext = Depends(require_perm("chat:send")),
    session: AsyncSession = Depends(get_session),
):
    result = await _run_turn(session, ctx, body, idempotency_key)
    return {
        "session_id": result["session_id"],
        "message_id": result["message_id"],
        "reply": result["reply"],
        "envelope": result["envelope"],
        "update_workspace": result.get("update_workspace", True),
    }


@router.post("/api/chat/stream")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ctx: UserContext = Depends(require_perm("chat:send")),
):
    async def generate():
        # The route dependency session is not available once the response
        # starts.  Keep this session alive for the entire turn.
        async with get_session_factory()() as session:
            handle = await start_turn(session, ctx, body, idempotency_key=idempotency_key)
            async for kind, payload in _live_turn_events(handle):
                if kind == "delta":
                    yield sse_frame("delta", {"text": payload.get("delta", "")})
                    continue
                if kind == "status":
                    yield sse_frame("status", payload)
                    continue
                yield sse_frame(
                    "result",
                    {
                        "session_id": payload["session_id"],
                        "message_id": payload["message_id"],
                        "reply": payload["reply"],
                        "envelope": payload["envelope"],
                        "update_workspace": payload.get("update_workspace", True),
                        "steps": payload.get("steps", []),
                    },
                )
                yield sse_frame("done", {"ok": bool(payload.get("ok"))})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/products")
async def products(
    ctx: UserContext = Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(FcstForecastResult.sku, FcstForecastResult.category)
            .where(FcstForecastResult.sku.is_not(None), FcstForecastResult.category.is_not(None))
            .order_by(FcstForecastResult.sku.asc())
        )
    ).all()
    seen: set[str] = set()
    result = []
    for sku, category in rows:
        key = str(sku)
        if key in seen:
            continue
        seen.add(key)
        result.append({"id": key, "sku": key, "name": key, "category": str(category), "brand": ""})
    return result


@router.get("/api/agent/probe/template")
async def probe_template(
    stream: bool = False,
    ctx: UserContext = Depends(require_perm("chat:read")),
):
    settings = get_settings()
    return {
        "url": settings.agent_api_url,
        "mode": "streaming" if stream else "blocking",
        "headers": {"Content-Type": "application/json"},
        "body": {"query": "", "response_mode": "streaming" if stream else "blocking", "inputs": {}},
    }


class ProbeRequest(BaseModel):
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/agent/probe")
async def probe_agent(
    payload: ProbeRequest,
    ctx: UserContext = Depends(require_perm("chat:read")),
):
    settings = get_settings()
    configured = bool(settings.agent_api_url and settings.agent_api_key)
    # This is intentionally a health/probe projection, not a second chat
    # loop.  Never echo supplied headers/body or any configured credential.
    return {
        "ok": configured,
        "mode": settings.agent_response_mode,
        "configured_mode": settings.agent_response_mode,
        "provider": "ml-gateway",
        "url": settings.agent_api_url,
        **({} if configured else {"error": "agent gateway is not configured"}),
    }


__all__ = ["ChatRequest", "SessionPatch", "router"]
