"""确定性看板触发集成单测（【变更自 T43】）。

驱动 run_flow（MockProvider + respx mock daemon），断言：
- query_sales_data 成功返回 dict rows → tool_result 事件 payload 附 dashboard_spec（且落库）；
- 返回空数据 → 无 dashboard_spec；
- 非 dashboard 工具（render_dashboard 已 helper 化不再调用，此处用 mock 侧验证不触发；
  实际以沙箱链 query/predict 为主）。
"""

import asyncio
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

from app.engine.flow import ActiveFlowRegistry
from app.engine.loop import RunContext, run_flow
from app.llm.mock_provider import MockProvider
from app.models import Conversation, Message, MessageEvent, Tool, User
from app.sse.hub import Hub, SSEStreamer
from app.tools.registry import create_tool
from app.tools.scenario import get_scenario

_SALES_ROWS = [
    {"month": "2026-02", "amount": 100},
    {"month": "2026-03", "amount": 120},
    {"month": "2026-04", "amount": 90},
]


async def _prepare_env(factory) -> tuple[str, str, object]:
    async with factory() as s:
        user = User(email=f"dt-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="DT")
        s.add(user)
        await s.flush()
        conv = Conversation(owner_id=user.id, title="dash-trigger")
        s.add(conv)
        await s.flush()
        scn = await get_scenario(s)
        existing = (await s.execute(select(Tool).where(Tool.name == "query_sales_data"))).scalars().first()
        if existing is None:
            await create_tool(
                s,
                name="query_sales_data",
                description="查询销量",
                input_schema={"type": "object", "properties": {"dimensions": {"type": "array", "items": {"type": "string"}}}, "required": ["dimensions"]},
                output_schema={"type": "object", "properties": {"rows": {"type": "array"}, "columns": {"type": "array"}}},
                execution={"kind": "sandbox", "image": "img:1", "handler": "q", "timeout_s": 5, "warm_pool": 0, "env_from_datasource": []},
                scenario_id=str(scn.id),
            )
        amsg = Message(conversation_id=conv.id, role="assistant", content="", status="running", trace_id=str(uuid.uuid4()))
        s.add(amsg)
        await s.commit()
        await s.refresh(conv)
        await s.refresh(amsg)
        await s.refresh(scn)
        return str(conv.id), str(amsg.id), scn


async def _run(factory, conv_id, mid, scn, loop_mod):
    registry = ActiveFlowRegistry()
    flow = await registry.register(conv_id)
    try:
        async with factory() as s:
            trace_id = str((await s.get(Message, mid)).trace_id)
        hub = Hub()
        streamer = SSEStreamer(conv_id)
        await hub.attach(conv_id, streamer)
        rctx = RunContext(
            conversation_id=conv_id, message_id=mid, trace_id=trace_id,
            scenario=scn, user_id="dt@corp.com", flow=flow, hub=hub,
            session_factory=factory,
        )
        result = await run_flow(rctx, "查询华东区最近 6 月销量", factory)
        events = []
        while True:
            try:
                events.append(streamer.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return result, events
    finally:
        await registry.release(conv_id)


@pytest.mark.asyncio
@respx.mock
async def test_query_success_attaches_dashboard_spec(db_session_factory, monkeypatch):
    respx.post("http://127.0.0.1:9000/run").mock(
        side_effect=lambda req: httpx.Response(
            200, json={"ok": True, "output": {"rows": _SALES_ROWS, "columns": ["month", "amount"]},
                       "container_id": "c1", "reused_warm": False, "exit_code": 0})
    )
    import app.engine.loop as loop_mod

    async def _mock_provider(*a, **k):
        return MockProvider("mock", "default", "")

    monkeypatch.setattr(loop_mod, "_resolve_provider", _mock_provider)

    factory = db_session_factory
    conv_id, mid, scn = await _prepare_env(factory)
    result, events = await _run(factory, conv_id, mid, scn, loop_mod)
    assert result["status"] == "completed", result

    tr = [e for e in events if e[0] == "tool.result"]
    assert tr, "应有 tool.result 事件"
    payload = tr[0][1]
    spec = payload.get("dashboard_spec")
    assert spec is not None
    assert spec["cards"][0]["card_type"] == "line"
    assert spec["cards"][0]["data"]["labels"] == ["2026-02", "2026-03", "2026-04"]

    # 落库 payload 也含 dashboard_spec（刷新经 getTrace 还原）
    async with factory() as s:
        evts = (await s.execute(select(MessageEvent).where(MessageEvent.message_id == mid).order_by(MessageEvent.seq))).scalars().all()
        tr_evt = next(e for e in evts if e.type == "tool_result")
        assert "dashboard_spec" in tr_evt.payload


@pytest.mark.asyncio
@respx.mock
async def test_query_empty_no_dashboard_spec(db_session_factory, monkeypatch):
    respx.post("http://127.0.0.1:9000/run").mock(
        side_effect=lambda req: httpx.Response(
            200, json={"ok": True, "output": {"rows": [], "columns": []},
                       "container_id": "c2", "reused_warm": False, "exit_code": 0})
    )
    import app.engine.loop as loop_mod

    async def _mock_provider(*a, **k):
        return MockProvider("mock", "default", "")

    monkeypatch.setattr(loop_mod, "_resolve_provider", _mock_provider)

    factory = db_session_factory
    conv_id, mid, scn = await _prepare_env(factory)
    result, events = await _run(factory, conv_id, mid, scn, loop_mod)
    assert result["status"] == "completed", result

    tr = [e for e in events if e[0] == "tool.result"]
    assert tr
    assert "dashboard_spec" not in tr[0][1]
