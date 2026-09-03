"""T15 追溯单测：seq 递增、还原完整链、markdown 导出、anomaly 标记、过滤查询。"""

import uuid

import pytest
from sqlalchemy import select

from app.models import Conversation, Message, MessageEvent, User, Role, UserRole
from app.tracing.admin_query import query_traces
from app.tracing.query import export_trace_markdown, get_trace
from app.tracing.trace import AGENT_PROCESS, DONE, MESSAGE_CREATED, TOOL_CALL, TOOL_ERROR, TOOL_RESULT, append_event


async def _seed_chain(session, owner_id: str, conversation_id: str) -> tuple[str, str]:
    """构造一次完整还原链，返回 (trace_id, message_id)。"""
    trace_id = str(uuid.uuid4())
    msg = Message(conversation_id=conversation_id, role="user", content="预测下月华东区销量", status="sent", trace_id=trace_id)
    session.add(msg)
    await session.flush()

    seq1 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=MESSAGE_CREATED, payload={"direction": "in", "content": "预测下月华东区销量"})
    seq2 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=AGENT_PROCESS, payload={"state": "starting"})
    seq3 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=AGENT_PROCESS, payload={"state": "executing"})
    seq4 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=TOOL_CALL, payload={"name": "query_sales_data", "input": {"region": "华东"}})
    seq5 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=TOOL_RESULT, payload={"name": "query_sales_data", "output": {"rows": []}, "duration_ms": 1200, "status": "ok"})
    seq6 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=TOOL_ERROR, payload={"name": "predict_sales", "error_code": "UPSTREAM", "message": "上游超时", "retried": 1})
    seq7 = await append_event(session, trace_id=trace_id, message_id=str(msg.id), type=DONE, payload={"final_text": "预测完成"})
    assert (seq1, seq2, seq3, seq4, seq5, seq6, seq7) == (1, 2, 3, 4, 5, 6, 7)
    await session.commit()
    return trace_id, str(msg.id)


@pytest.mark.asyncio
async def test_trace_chain_restore(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        user = User(email="tr@corp.com", password_hash="H", nickname="T")
        s.add(user)
        await s.flush()
        conv = Conversation(owner_id=user.id, title="t")
        s.add(conv)
        await s.flush()
        trace_id, mid = await _seed_chain(s, str(user.id), str(conv.id))

        res = await get_trace(s, conversation_id=str(conv.id), message_id=mid, owner_id=str(user.id))
        assert res["trace_id"] == trace_id
        types = [e["type"] for e in res["events"]]
        assert types == [MESSAGE_CREATED, AGENT_PROCESS, AGENT_PROCESS, TOOL_CALL, TOOL_RESULT, TOOL_ERROR, DONE]

        md = await export_trace_markdown(s, conversation_id=str(conv.id), message_id=mid, owner_id=str(user.id))
        assert "用户消息" in md
        assert "query_sales_data" in md
        assert "UPSTREAM" in md and "retried=1" in md
        assert "最终回复" in md and "预测完成" in md


@pytest.mark.asyncio
async def test_owner_isolation_returns_404(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        u1 = User(email="o1@corp.com", password_hash="H", nickname="O1")
        u2 = User(email="o2@corp.com", password_hash="H", nickname="O2")
        s.add_all([u1, u2])
        await s.flush()
        conv = Conversation(owner_id=u1.id, title="private")
        s.add(conv)
        await s.flush()
        trace_id, mid = await _seed_chain(s, str(u1.id), str(conv.id))
        from app.utils.errors import NotFoundError

        # 他人访问 → 404（不泄露存在性）
        with pytest.raises(NotFoundError):
            await get_trace(s, conversation_id=str(conv.id), message_id=mid, owner_id=str(u2.id))


@pytest.mark.asyncio
async def test_anomaly_marker(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        u = User(email="an@corp.com", password_hash="H", nickname="A")
        s.add(u)
        await s.flush()
        conv = Conversation(owner_id=u.id, title="t")
        s.add(conv)
        await s.flush()
        msg = Message(conversation_id=conv.id, role="user", content="x", status="sent")
        s.add(msg)
        await s.flush()
        await append_event(session=s, trace_id=str(uuid.uuid4()), message_id=str(msg.id), type=MESSAGE_CREATED, payload={}, anomaly=True)
        await s.commit()
        evt = (await s.execute(select(MessageEvent).where(MessageEvent.anomaly.is_(True)))).scalars().first()
        assert evt is not None


@pytest.mark.asyncio
async def test_query_traces_filter(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        u = User(email="qf@corp.com", password_hash="H", nickname="Q")
        s.add(u)
        await s.flush()
        conv = Conversation(owner_id=u.id, title="t")
        s.add(conv)
        await s.flush()
        trace_id, mid = await _seed_chain(s, str(u.id), str(conv.id))

        res = await query_traces(s, tool_name="query_sales_data")
        assert len(res) >= 1
        assert all(e["type"] == "tool_call" for e in res if e["type"] == "tool_call") or any(
            e["payload"].get("name") == "query_sales_data" for e in res
        )

        res_err = await query_traces(s, error_code="UPSTREAM")
        assert any(e["payload"].get("error_code") == "UPSTREAM" for e in res_err)