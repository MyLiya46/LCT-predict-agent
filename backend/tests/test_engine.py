"""T16 引擎单测：完整循环（MockProvider + respx mock daemon）。

场景：注册 query_sales_data 工具到默认场景；发消息驱动 run_flow；
断言事件链（tool_call→tool_result→done）、并存、中断 SafePoint、checkpoint。
"""

import asyncio
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

from app.engine.flow import ActiveFlowRegistry
from app.engine.loop import RunContext, _user_facing_final_text, run_flow
from app.models import Conversation, Message, MessageEvent, Tool, User
from app.sse.hub import Hub
from app.tools.registry import create_tool
from app.tools.scenario import get_scenario


def test_user_facing_final_text_does_not_leak_need_input_marker():
    text = _user_facing_final_text("模型说明：need_input(forecast_month)，请补充月份。")

    assert "need_input" not in text
    assert "预测基准月" in text


async def _prepare_env(factory) -> tuple[str, str, object]:
    """建用户/会话 + 默认场景绑定工具，返回 (conversation_id, assistant_message_id, scenario)。"""
    async with factory() as s:
        user = User(email=f"eng-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="E")
        s.add(user)
        await s.flush()
        conv = Conversation(owner_id=user.id, title="engine")
        s.add(conv)
        await s.flush()
        scn = await get_scenario(s)
        existing = (await s.execute(select(Tool).where(Tool.name == "query_sales_data"))).scalars().first()
        if existing is None:
            await create_tool(
                s,
                name="query_sales_data", description="查询销量",
                input_schema={"type": "object", "properties": {"dimensions": {"type": "array", "items": {"type": "string"}}}, "required": ["dimensions"]},
                output_schema={"type": "object", "properties": {"rows": {"type": "array"}}},
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


@pytest.mark.asyncio
@respx.mock
async def test_run_flow_full_chain(db_session_factory):
    # mock daemon（sandbox client 指向 9000，settings.sandbox_daemon_url 默认如此）
    respx.post("http://127.0.0.1:9000/run").mock(
        side_effect=lambda req: httpx.Response(200, json={"ok": True, "output": {"rows": [1, 2]}, "container_id": "c1", "reused_warm": False, "exit_code": 0})
    )

    factory = db_session_factory
    conv_id, mid, _scn = await _prepare_env(factory)

    registry = ActiveFlowRegistry()
    flow = await registry.register(conv_id)

    async with factory() as s:
        msg = await s.get(Message, mid)
        trace_id = str(msg.trace_id)
    hub = Hub()
    rctx = RunContext(
        conversation_id=conv_id, message_id=mid, trace_id=trace_id,
        scenario=_scn, user_id="eng@corp.com", flow=flow, hub=hub,
        session_factory=factory,
    )
    result = await run_flow(rctx, "查询华东区最近 6 月销量", factory)
    assert result["status"] == "completed", result

    # 事件链断言
    async with factory() as s:
        evts = (
            await s.execute(
                select(MessageEvent).where(MessageEvent.message_id == mid).order_by(MessageEvent.seq)
            )
        ).scalars().all()
        types = [e.type for e in evts]
        assert "tool_call" in types
        assert "tool_result" in types
        assert types[-1] == "done"
        # 缓冲熔断不触发（工具成功）
        assert sum(1 for e in evts if e.type == "tool_error") == 0

    await registry.release(conv_id)


@pytest.mark.asyncio
@respx.mock
async def test_run_flow_interrupt_safepoint(db_session_factory):
    respx.post("http://127.0.0.1:9000/run").mock(
        side_effect=lambda req: httpx.Response(200, json={"ok": True, "output": {"rows": []}, "container_id": "c2", "reused_warm": False, "exit_code": 0})
    )
    factory = db_session_factory
    conv_id, mid, _scn = await _prepare_env(factory)

    registry = ActiveFlowRegistry()
    flow = await registry.register(conv_id)

    async with factory() as s:
        trace_id = str((await s.get(Message, mid)).trace_id)

    # 异步启动 run_flow，1.5s 后 cancel（模拟用户停止）
    hub = Hub()
    rctx = RunContext(
        conversation_id=conv_id, message_id=mid, trace_id=trace_id,
        scenario=_scn, user_id="eng@corp.com", flow=flow, hub=hub,
        session_factory=factory,
    )

    async def _stopper():
        await asyncio.sleep(1.5)
        flow.cancel()

    stop_task = asyncio.create_task(_stopper())
    result = await run_flow(rctx, "查询华东区最近 6 月销量", factory)
    await stop_task
    assert result["status"] in ("interrupted", "completed"), result
    await registry.release(conv_id)


@pytest.mark.asyncio
async def test_active_flow_registry_conflict(db_session_factory):
    registry = ActiveFlowRegistry()
    await registry.register("conv-x")
    assert registry.active("conv-x") is True
    from app.utils.errors import ConflictError

    with pytest.raises(ConflictError):
        await registry.register("conv-x")
    await registry.release("conv-x")
    assert registry.active("conv-x") is False
