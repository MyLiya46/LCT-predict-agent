"""审计 / 会话 / 消息 / 追溯只读检索路由（T20 / tech_design §3.11.4）。

所有只读检索本身留痕（audit.view），绝不写业务数据。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_perm
from app.auth.tokens import UserContext
from app.database import get_session
from app.domain.chat_service import admin_list_messages, admin_list_sessions
from app.models import AuditLog, MessageEvent
from app.tracing.admin_query import query_traces
from app.tracing.audit import AUDIT_VIEW, write_audit
from app.utils.errors import NotFoundError, to_uni

router = APIRouter(
    prefix="", tags=["admin-audit"],
    dependencies=[Depends(require_perm("audit:read"))],
)


async def _mark_view(
    ctx: UserContext, request: Request, target_type: str, filter_summary: str
) -> None:
    """检索即留痕（audit.view；写自身不触发递归）。"""
    await write_audit(
        actor_id=ctx.id, actor_email=ctx.email, action=AUDIT_VIEW,
        target_type=target_type, target_id=ctx.id,
        ip=request.client.host if request.client else "",
        detail={"target": target_type, "filters": filter_summary},
    )


@router.get("/conversations/{cid}/stream")
async def conversation_stream(
    cid: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """管理员端会话级事件流 SSE（Live Tail，只读）：audit:read 由路由前缀依赖保证，
    订阅即 audit.view 留痕一次；会话只需存在，不校验 owner。"""
    from app.models import Conversation

    conv = await session.get(Conversation, cid)
    if conv is None or conv.status == "deleted":
        raise NotFoundError("会话不存在")
    await _mark_view(ctx, request, "session", f"cid={cid}")

    from app.domain.chat_service import _get_hub
    from app.sse.hub import SSEStreamer
    from app.sse.session import live_stream, prepare_replay

    hub = _get_hub()
    streamer = SSEStreamer(cid)
    await hub.attach(cid, streamer)
    replay_frames, meta_frame, current_turn = await prepare_replay(session, cid)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        live_stream(hub, cid, streamer, replay_frames, meta_frame, current_turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
async def list_sessions(
    q: Optional[str] = None, status: Optional[str] = None,
    owner_email: Optional[str] = None, cursor: Optional[str] = None, limit: int = 20,
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    request: Request = Request,
):
    data = await admin_list_sessions(session, q=q, status=status, cursor=cursor, limit=min(limit, 100))
    await _mark_view(ctx, request, "session", f"q={q};status={status}")
    return to_uni(data)


@router.get("/messages")
async def list_admin_messages(
    q: Optional[str] = None, status: Optional[str] = None,
    owner_email: Optional[str] = None, cursor: Optional[str] = None, limit: int = 20,
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    request: Request = Request,
):
    data = await admin_list_messages(session, q=q, status=status, owner_email=owner_email, cursor=cursor, limit=min(limit, 100))
    await _mark_view(ctx, request, "message", f"q={q};owner={owner_email}")
    return to_uni(data)


@router.get("/traces")
async def list_traces(
    trace_id: Optional[str] = None, tool_name: Optional[str] = None,
    error_code: Optional[str] = None, actor_email: Optional[str] = None,
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    request: Request = Request,
):
    rows = await query_traces(
        session, trace_id=trace_id, tool_name=tool_name, error_code=error_code, actor_email=actor_email
    )
    await _mark_view(ctx, request, "trace", f"tool={tool_name};err={error_code}")
    return to_uni({"items": rows})


@router.get("/traces/{trace_id}")
async def trace_detail(
    trace_id: str = Path(...),
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(MessageEvent).where(MessageEvent.trace_id == trace_id).order_by(MessageEvent.seq)
        )
    ).scalars().all()
    if not rows:
        raise NotFoundError("追溯记录不存在")
    events = [
        {
            "seq": e.seq, "type": e.type, "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]
    return to_uni({"trace_id": trace_id, "events": events})


@router.get("/audits")
async def list_audits(
    type: Optional[str] = None, actor: Optional[str] = None,
    target: Optional[str] = None, cursor: Optional[str] = None, limit: int = 20,
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    request: Request = Request,
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 100))
    if type:
        stmt = stmt.where(AuditLog.action == type)
    if actor:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    rows = list((await session.execute(stmt)).scalars().all())
    items = [
        {
            "id": str(a.id), "actor_id": str(a.actor_id) if a.actor_id else None,
            "actor_email": a.actor_email, "action": a.action,
            "target_type": a.target_type, "target_id": str(a.target_id) if a.target_id else None,
            "ip": a.ip, "detail": a.detail,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]
    await _mark_view(ctx, request, "audit", f"action={type};actor={actor}")
    return to_uni({"items": items})


@router.get("/audits/{audit_id}")
async def audit_detail(
    audit_id: str = Path(...),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(AuditLog, audit_id)
    if row is None:
        raise NotFoundError("审计记录不存在")
    return to_uni(
        {
            "id": str(row.id), "actor_id": str(row.actor_id) if row.actor_id else None,
            "actor_email": row.actor_email, "action": row.action,
            "target_type": row.target_type, "target_id": str(row.target_id) if row.target_id else None,
            "ip": row.ip, "detail": row.detail,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    )


@router.post("/audits/export")
async def audits_export():
    """P1 占位（PRD P1-7）。"""
    return to_uni({"message": "审计导出为 P1 功能，本期未提供"}, code="501_NOT_IMPLEMENTED")
