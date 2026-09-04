"""Bridge native backup chat events to the workbench chat façade."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import UserContext
from app.domain.chat_service import (
    DEFAULT_CONVERSATION_TITLE,
    _get_hub,
    create_conversation,
    get_conversation,
    send_message,
    stop_message,
)
from app.models import Message, MessageEvent
from app.services.chat_envelope import build_envelope
from app.services.memory import update_memory
from app.sse.hub import Hub, SSEStreamer

# Forecast model cold starts may take a little over two minutes.  Keep the
# façade alive long enough for the internal forecast tool to finish while the
# tool itself remains bounded by the same 300-second ceiling.
CHAT_TURN_TIMEOUT_S = 300.0
_STAGE_TEXT = {
    "starting": "正在启动对话…",
    "planning": "正在分析问题…",
    "executing": "正在调用数据能力…",
    "retrying": "正在重试…",
    "degrading": "模型服务降级处理中…",
    "interrupted": "已停止处理",
    "done": "处理完成",
}


@dataclass
class TurnHandle:
    session: AsyncSession
    ctx: UserContext
    conversation_id: str
    message_id: str
    trace_id: str | None
    hub: Hub
    streamer: SSEStreamer
    status_events: list[dict[str, Any]] = field(default_factory=list)
    detached: bool = False


def _status_event(
    state: str,
    steps: list[str],
    *,
    detail: str | None = None,
    custom_text: str | None = None,
) -> dict[str, Any]:
    text = custom_text or _STAGE_TEXT.get(state, detail or state)
    if detail and state not in _STAGE_TEXT and custom_text is None:
        text = detail
    if text and (not steps or steps[-1] != text):
        steps.append(text)
    del steps[:-40]
    return {"stage": state, "text": text, "steps": list(steps)}


def native_event_to_status(event: str, data: dict[str, Any], steps: list[str]) -> dict[str, Any] | None:
    if event in {"agent.process", "agent.status"}:
        state = str(data.get("state") or data.get("stage") or "")
        return _status_event(state, steps, detail=data.get("detail")) if state else None
    if event == "tool.call":
        name = str(data.get("name") or "tool")
        return _status_event("executing", steps, custom_text=f"正在调用 {name}…")
    if event == "tool.result":
        name = str(data.get("name") or "tool")
        return _status_event("executing", steps, custom_text=f"已完成 {name}")
    if event == "tool.error":
        return _status_event("retrying", steps, detail=data.get("message"))
    if event == "done":
        return _status_event("done", steps)
    return None


async def start_turn(
    session: AsyncSession,
    ctx: UserContext,
    body: Any,
    *,
    idempotency_key: str | None = None,
) -> TurnHandle:
    conversation_id = getattr(body, "session_id", None)
    if conversation_id:
        conv = await get_conversation(session, str(conversation_id), ctx.id)
    else:
        conv = await create_conversation(session, ctx.id, DEFAULT_CONVERSATION_TITLE)
    cid = str(conv.id)
    hub = _get_hub()
    streamer = SSEStreamer(cid)
    await hub.attach(cid, streamer)
    try:
        sent = await send_message(
            session,
            conversation_id=cid,
            owner_id=ctx.id,
            content=body.message,
            idem_key=idempotency_key,
            oa=getattr(body, "oa", None),
            oauth_access_token=getattr(body, "access_token", None),
        )
    except BaseException:
        await hub.detach(cid, streamer)
        streamer.close()
        raise
    return TurnHandle(
        session=session,
        ctx=ctx,
        conversation_id=cid,
        message_id=str(sent["message_id"]),
        trace_id=str(sent["trace_id"]) if sent.get("trace_id") else None,
        hub=hub,
        streamer=streamer,
    )


async def _detach(handle: TurnHandle) -> None:
    if not handle.detached:
        handle.detached = True
        await handle.hub.detach(handle.conversation_id, handle.streamer)
        handle.streamer.close()


async def _events_for(handle: TurnHandle) -> list[MessageEvent]:
    if not handle.trace_id:
        return []
    result = await handle.session.execute(
        select(MessageEvent)
        .where(
            MessageEvent.trace_id == handle.trace_id,
            MessageEvent.message_id == handle.message_id,
        )
        .order_by(MessageEvent.seq)
    )
    return list(result.scalars().all())


async def _finish_failure(handle: TurnHandle, text: str, status: str = "failed") -> dict[str, Any]:
    try:
        await stop_message(handle.session, handle.conversation_id, handle.message_id, handle.ctx.id)
    except Exception:
        pass
    msg = await handle.session.get(Message, handle.message_id)
    if msg is not None:
        msg.content = text
        msg.status = status
        msg.result_envelope = build_envelope(text, [], handle.status_events[-1].get("steps", []) if handle.status_events else [], status)
        await handle.session.commit()
    return {"final_text": text, "status": status, "tool_outputs": []}


async def collect_turn(
    handle: TurnHandle,
    *,
    timeout_s: float = CHAT_TURN_TIMEOUT_S,
    on_status: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> dict[str, Any]:
    """Consume only native events, then persist one normalized terminal result."""
    final: dict[str, Any] | None = None
    steps: list[str] = []
    try:
        async with asyncio.timeout(timeout_s):
            while final is None:
                item = await handle.streamer.recv()
                if item is None:
                    continue
                event, data, _seq = item
                if event == "message.delta":
                    delta = str(data.get("text") or "")
                    if delta and on_status is not None:
                        maybe = on_status(
                            {
                                "stage": "answering",
                                "text": delta,
                                "delta": delta,
                                "steps": list(steps),
                            }
                        )
                        if maybe is not None:
                            await maybe
                    continue
                status = native_event_to_status(event, data, steps)
                if status is not None:
                    handle.status_events.append(status)
                    if on_status is not None:
                        maybe = on_status(status)
                        if maybe is not None:
                            await maybe
                if event == "error":
                    final = await _finish_failure(
                        handle,
                        str(data.get("message") or "执行失败，请重试。"),
                        "failed",
                    )
                elif event == "done":
                    final = {
                        "final_text": str(data.get("final_text") or data.get("message") or ""),
                        "status": str(data.get("status") or ("failed" if event == "error" else "completed")),
                        "tool_outputs": [],
                    }
    except asyncio.TimeoutError:
        final = await _finish_failure(handle, "本次处理超时，请稍后重试。")
    except asyncio.CancelledError:
        await _finish_failure(handle, "已停止处理", "interrupted")
        await _detach(handle)
        raise
    except Exception:
        final = await _finish_failure(handle, "执行失败，请重试。")

    events = await _events_for(handle)
    outputs = [
        {"name": evt.payload.get("name"), "output": evt.payload.get("output"), "status": evt.payload.get("status")}
        for evt in events
        if evt.type == "tool_result" and evt.payload.get("status") == "ok"
    ]
    final["tool_outputs"] = outputs
    final_text = final.get("final_text", "")
    status = final.get("status", "failed")
    envelope = build_envelope(final_text, outputs, steps, status)
    msg = await handle.session.get(Message, handle.message_id)
    if msg is not None:
        msg.content = final_text
        msg.status = status
        msg.result_envelope = envelope
        if status == "completed":
            await update_memory(handle.session, handle.conversation_id, owner_id=handle.ctx.id, capability=envelope["response_type"], commit=False)
        await handle.session.commit()
    await _detach(handle)
    return {
        "session_id": handle.conversation_id,
        "message_id": handle.message_id,
        "reply": final_text,
        "envelope": envelope,
        "update_workspace": envelope.get("update_workspace", True),
        "steps": steps[-40:],
        "status_events": handle.status_events,
        "ok": status == "completed",
    }


__all__ = ["CHAT_TURN_TIMEOUT_S", "TurnHandle", "collect_turn", "native_event_to_status", "start_turn"]
