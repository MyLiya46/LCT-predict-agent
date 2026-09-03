"""T38 会话级事件流 SSE 单测（回放/包装/token 累计 + 双端权限）。

- prepare_replay：回放顺序（seq 升序、turn_index 跨 trace 稳定）、sse_opened 剔除、
  超 200 只回放最近 200、session.meta 的 event_total/token_total。
- live_stream：实时事件包装为 session.pack（字段齐全）。
- 双端权限（HTTP）：用户跨会话 404 无审计、未登录 401、admin 无 audit:read 403 +
  authz.denied、admin 订阅任意会话 200 且 audit.view 留痕。
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.auth.password import hash_password
from app.auth.tokens import create_token
from app.models import (
    AuditLog,
    Conversation,
    Message,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.rbac.service import load_user_ctx
from app.sse.hub import Hub, SSEStreamer
from app.sse.session import live_stream, prepare_replay
from app.tracing.trace import DONE, MESSAGE_CREATED, SSE_OPENED, TOOL_CALL, TOOL_RESULT, append_event


async def _seed_trace(factory, conv, t: int) -> None:
    """为一个 turn 写 4 条事件（message_created/tool_call/tool_result/done 带 usage）。"""
    async with factory() as s:
        trace_id = str(uuid.uuid4())
        um = Message(conversation_id=conv.id, role="user", content=f"q{t}", status="sent", trace_id=trace_id)
        am = Message(conversation_id=conv.id, role="assistant", content=f"a{t}", status="completed", trace_id=trace_id)
        s.add_all([um, am])
        await s.flush()
        await append_event(s, trace_id=trace_id, message_id=str(um.id), type=MESSAGE_CREATED, payload={"content": f"q{t}"})
        await append_event(s, trace_id=trace_id, message_id=str(am.id), type=TOOL_CALL, payload={"name": "query_sales_data", "input": {}, "plan_index": 0, "request_id": f"r{t}"})
        await append_event(s, trace_id=trace_id, message_id=str(am.id), type=TOOL_RESULT, payload={"name": "query_sales_data", "output": {"rows": []}, "duration_ms": 12, "status": "ok"})
        await append_event(s, trace_id=trace_id, message_id=str(am.id), type=DONE, payload={"final_text": f"a{t}", "status": "completed", "usage": {"prompt_tokens": 120, "completion_tokens": 80}})
        await s.commit()


async def _mk_conversation(factory, title: str) -> tuple[str, Conversation]:
    async with factory() as s:
        user = User(email=f"ss-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="S")
        s.add(user)
        await s.flush()
        conv = Conversation(owner_id=user.id, title=title)
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        return str(user.id), conv


def _packs(frames: list[str]) -> list[dict]:
    out = []
    for f in frames:
        for line in f.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def _meta_payload(meta_frame: str) -> dict:
    return json.loads(meta_frame.split("data: ")[1])


@pytest.mark.asyncio
async def test_prepare_replay_order_turn_and_meta(db_session_factory):
    factory = db_session_factory
    _uid, conv = await _mk_conversation(factory, "replay")
    await _seed_trace(factory, conv, 1)
    await _seed_trace(factory, conv, 2)

    async with factory() as s:
        frames, meta_frame, current_turn = await prepare_replay(s, str(conv.id))

    packs = _packs(frames)
    assert len(packs) == 8
    assert [p["turn_index"] for p in packs[:4]] == [1, 1, 1, 1]
    assert [p["turn_index"] for p in packs[4:]] == [2, 2, 2, 2]
    assert [p["seq"] for p in packs] == [1, 2, 3, 4, 1, 2, 3, 4]
    assert packs[-1]["event_type"] == "done"
    assert packs[-1]["payload"]["usage"] == {"prompt_tokens": 120, "completion_tokens": 80}

    meta = _meta_payload(meta_frame)
    assert meta["conversation_id"] == str(conv.id)
    assert meta["event_total"] == 8
    assert meta["token_total"] == 400
    assert current_turn == 2


@pytest.mark.asyncio
async def test_prepare_replay_excludes_sse_opened_and_limits_200(db_session_factory):
    factory = db_session_factory
    _uid, conv = await _mk_conversation(factory, "limit")

    async with factory() as s:
        trace_id = str(uuid.uuid4())
        am = Message(conversation_id=conv.id, role="assistant", content="", status="completed", trace_id=trace_id)
        s.add(am)
        await s.flush()
        for i in range(205):
            await append_event(s, trace_id=trace_id, message_id=str(am.id), type=TOOL_CALL, payload={"name": "t", "index": i})
        await append_event(s, trace_id=trace_id, message_id=str(am.id), type=SSE_OPENED, payload={})
        await s.commit()

        frames, meta_frame, _turn = await prepare_replay(s, str(conv.id))

    packs = _packs(frames)
    assert len(packs) == 200
    assert all(p["event_type"] != "sse.opened" for p in packs)
    assert _meta_payload(meta_frame)["event_total"] == 205  # sse_opened 不计入可见总数


@pytest.mark.asyncio
async def test_live_stream_wraps_realtime(db_session_factory):
    factory = db_session_factory
    cid = "conv-live"
    hub = Hub()

    async with factory() as s:
        _frames, meta_frame, _turn = await prepare_replay(s, cid)  # 空会话

    streamer = SSEStreamer(cid)
    await hub.attach(cid, streamer)
    await hub.publish(cid, "tool.call", {"name": "x", "input": {}, "plan_index": 0, "request_id": "r2"}, seq=2)

    gen = live_stream(hub, cid, streamer, [], meta_frame, 0)
    # 首帧 = meta，次帧 = 实时包装
    first = await gen.__anext__()
    second = await gen.__anext__()
    await gen.aclose()

    assert "event: session.meta" in first
    assert "event: session.pack" in second
    data = json.loads(second.split("data: ")[1])
    assert data["event_type"] == "tool.call"
    assert data["payload"]["name"] == "x"
    assert data["seq"] == 2
    assert set(data) == {"event_type", "payload", "seq", "turn_index", "ts"}


# ------------------------------------------------------------------
# 双端权限（HTTP）
# ------------------------------------------------------------------
def _build_app():
    from fastapi import FastAPI

    from app.api import admin as admin_routes
    from app.api import chat
    from app.middleware.rbac import AdminPrefixMiddleware
    from app.utils.errors import register_exception_handlers

    app = FastAPI()
    app.add_middleware(AdminPrefixMiddleware)
    register_exception_handlers(app)
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(admin_routes.audits.router, prefix="/api/v1/admin")
    return app


async def _mk_user_token(factory, email: str, perm_codes: list[str]) -> tuple[str, str]:
    async with factory() as s:
        perm_by_code = {p.code: p for p in (await s.execute(select(Permission))).scalars().all()}
        user = User(email=email, password_hash=hash_password("Passw0rd123"), nickname="U", status="active")
        s.add(user)
        await s.flush()
        role = Role(code=f"role-{uuid.uuid4().hex[:8]}", name="R", builtin=False)
        s.add(role)
        await s.flush()
        for code in perm_codes:
            if code in perm_by_code:
                s.add(RolePermission(role_id=role.id, permission_id=perm_by_code[code].id))
        s.add(UserRole(user_id=user.id, role_id=role.id))
        await s.commit()
        ctx = await load_user_ctx(s, str(user.id))
        token = create_token(user, "access", ctx.roles, ctx.perms)
        return str(user.id), token


async def _count_audit(factory, action: str) -> int:
    async with factory() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
        return len(rows)


@pytest.mark.asyncio
async def test_user_cross_subscribe_404_no_audit(db_session_factory):
    factory = db_session_factory
    app = _build_app()
    a_id, _ = await _mk_user_token(factory, f"a-{uuid.uuid4().hex[:8]}@corp.com", ["chat:read", "chat:send"])
    _b_id, b_tok = await _mk_user_token(factory, f"b-{uuid.uuid4().hex[:8]}@corp.com", ["chat:read"])

    async with factory() as s:
        conv = Conversation(owner_id=a_id, title="A")
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        cid = str(conv.id)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/v1/chat/conversations/{cid}/stream", headers={"Authorization": f"Bearer {b_tok}"})
        assert r.status_code == 404

    assert await _count_audit(factory, "audit.view") == 0


@pytest.mark.asyncio
async def test_unauthenticated_401(db_session_factory):
    _ = db_session_factory
    app = _build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/chat/conversations/any/stream")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_without_audit_read_403(db_session_factory):
    factory = db_session_factory
    app = _build_app()
    _uid, tok = await _mk_user_token(factory, f"ops-{uuid.uuid4().hex[:8]}@corp.com", ["adm:user.manage", "chat:read"])

    async with factory() as s:
        conv = Conversation(owner_id=_uid, title="x")
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        cid = str(conv.id)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/v1/admin/conversations/{cid}/stream", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403
        assert r.json()["code"] == "403_FORBIDDEN"

    assert await _count_audit(factory, "authz.denied") >= 1


@pytest.mark.asyncio
async def test_admin_subscribe_200_audit_view(db_session_factory, monkeypatch):
    factory = db_session_factory
    app = _build_app()
    _admin_id, admin_tok = await _mk_user_token(
        factory, f"adm-{uuid.uuid4().hex[:8]}@corp.com",
        ["audit:read", "adm:user.manage"],
    )
    owner_id, _ = await _mk_user_token(factory, f"own-{uuid.uuid4().hex[:8]}@corp.com", ["chat:read"])

    async with factory() as s:
        conv = Conversation(owner_id=owner_id, title="owned")
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        cid = str(conv.id)

    # httpx.ASGITransport buffers a StreamingResponse until its generator
    # completes, while a live-tail stream is intentionally unbounded.  Keep
    # this HTTP auth/audit test bounded at the initial metadata frame; the
    # production live-tail behavior is covered directly above.
    from app.sse import session as session_sse

    original_live_stream = session_sse.live_stream

    async def bounded_live_stream(*args, **kwargs):
        inner = original_live_stream(*args, **kwargs)
        try:
            async for frame in inner:
                yield frame
                if "event: session.meta" in frame:
                    break
        finally:
            await inner.aclose()

    monkeypatch.setattr(session_sse, "live_stream", bounded_live_stream)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with c.stream(
            "GET", f"/api/v1/admin/conversations/{cid}/stream",
            headers={"Authorization": f"Bearer {admin_tok}"},
        ) as resp:
            assert resp.status_code == 200
            body = await resp.aread()
            assert "event: session.meta" in body.decode()

    assert await _count_audit(factory, "audit.view") >= 1
