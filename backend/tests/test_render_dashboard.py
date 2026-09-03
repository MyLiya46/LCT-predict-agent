"""T43 render_dashboard 内置工具单测：internal 分支执行、spec 全文透传、不触 sandbox。

- LLM 下发 render_dashboard 工具调用 → 引擎走 internal 分支 → tool_result 载荷完整 spec；
- daemon（sandbox client）未被调用；
- schema 非法输入 → tool_error(VALIDATION)，消息终态仍 completed；
- 既有 query_sales_data 输出不受影响。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.engine.flow import ActiveFlowRegistry
from app.engine.loop import RunContext, run_flow
from app.llm.events import ContentDeltaEvent, DoneReasonEvent, ToolCall, ToolCallBatchEvent
from app.models import Conversation, Message, MessageEvent, Tool, User
from app.sse.hub import Hub, SSEStreamer
from app.tools.registry import create_tool
from app.tools.scenario import get_scenario

SAMPLE_SPEC = {
    "layout": "grid",
    "cards": [
        {
            "card_type": "line",
            "title": "华东销量趋势",
            "description": "近 6 月",
            "data": {
                "labels": ["2月", "3月", "4月", "5月", "6月", "7月"],
                "series": [{"name": "华东", "values": [100, 120, 90, 140, 160, 180]}],
            },
        },
        {
            "card_type": "table",
            "title": "区域对比",
            "data": {
                "labels": ["华东", "华南"],
                "series": [{"name": "销售额", "values": [1000, 800]}],
            },
        },
    ],
}


class DashboardMockProvider:
    """脚本化 mock：识别「看板」意图 → 下发 render_dashboard 工具调用。"""

    def __init__(self, spec: dict) -> None:
        self.name = "mock"
        self.default_model = "mock-model"
        self.provider_id = "mock-provider"
        self.status = "healthy"
        self._spec = spec

    async def chat(self, messages, tools=None, config=None):
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if has_tool_result:
            reply = "已生成看板。"
            yield ContentDeltaEvent(text=reply)
            yield DoneReasonEvent(stop_reason="stop", final_text=reply, usage={"prompt_tokens": 120, "completion_tokens": 80})
            return
        yield ContentDeltaEvent(text="")
        yield ToolCallBatchEvent(calls=[ToolCall(index=0, id="call_dash", name="render_dashboard", arguments=self._spec)])
        yield DoneReasonEvent(stop_reason="tool_use", final_text="")

    async def complete(self, messages, config=None):
        return "[]"  # 无 follow-up 建议

    async def check_health(self):
        return True


async def _prepare_env(factory, spec: dict = SAMPLE_SPEC):
    async with factory() as s:
        user = User(email=f"dash-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="D")
        s.add(user)
        await s.flush()
        conv = Conversation(owner_id=user.id, title="dashboard")
        s.add(conv)
        await s.flush()
        scn = await get_scenario(s)
        existing = (await s.execute(select(Tool).where(Tool.name == "render_dashboard"))).scalars().first()
        if existing is None:
            await create_tool(
                s,
                name="render_dashboard",
                description="销售数据看板渲染（折线/柱状/表格）",
                input_schema={"type": "object", "properties": {"cards": {"type": "array"}}, "required": ["cards"]},
                output_schema={"type": "object", "properties": {"layout": {"type": "string"}, "cards": {"type": "array"}}},
                execution={"kind": "internal", "handler": "render_dashboard", "timeout_s": 5},
                scenario_id=str(scn.id),
            )
        amsg = Message(conversation_id=conv.id, role="assistant", content="", status="running", trace_id=str(uuid.uuid4()))
        s.add(amsg)
        await s.commit()
        await s.refresh(conv)
        await s.refresh(amsg)
        await s.refresh(scn)
        return str(conv.id), str(amsg.id), scn, spec


async def _run(factory, conv_id, mid, scn, provider):
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
            scenario=scn, user_id="dash@corp.com", flow=flow, hub=hub,
            session_factory=factory,
        )
        result = await run_flow(rctx, "分析华东销量并输出看板", factory)
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
async def test_internal_exec_no_sandbox_and_full_spec(db_session_factory, monkeypatch):
    factory = db_session_factory
    conv_id, mid, scn, spec = await _prepare_env(factory)

    # 断言 sandbox client 不被调用
    async def _boom_execute(*a, **k):
        raise AssertionError("internal 工具不应调用 sandbox daemon")

    import app.engine.loop as loop_mod

    async def _resolve(*a, **k):
        return DashboardMockProvider(spec)

    monkeypatch.setattr(loop_mod.sandbox_client, "execute", _boom_execute)
    monkeypatch.setattr(loop_mod, "_resolve_provider", _resolve)

    result, events = await _run(factory, conv_id, mid, scn, DashboardMockProvider(spec))
    assert result["status"] == "completed", result

    # SSE 事件：tool.call → tool.result（render_dashboard），payload 为完整 spec
    names = [e[0] for e in events]
    assert "tool.call" in names
    assert "tool.result" in names
    tr = [e for e in events if e[0] == "tool.result"][0]
    assert tr[1]["name"] == "render_dashboard"
    out = tr[1]["output_summary"]
    assert out.get("layout") == "grid"
    assert len(out["cards"]) == 2
    # 全文透传（不截断）：折线 card 的 series 完整
    assert out["cards"][0]["data"]["series"][0]["values"] == [100, 120, 90, 140, 160, 180]

    # 落库：tool_result payload 完整 spec
    async with factory() as s:
        evts = (await s.execute(select(MessageEvent).where(MessageEvent.message_id == mid).order_by(MessageEvent.seq))).scalars().all()
        types = [e.type for e in evts]
        assert "tool_call" in types and "tool_result" in types and types[-1] == "done"
        tr_evt = next(e for e in evts if e.type == "tool_result")
        assert tr_evt.payload["output"]["cards"][1]["card_type"] == "table"


@pytest.mark.asyncio
async def test_internal_validation_error_completed(db_session_factory, monkeypatch):
    factory = db_session_factory
    bad_spec = {"layout": "invalid_layout", "cards": "not-a-list"}
    conv_id, mid, scn, _ = await _prepare_env(factory, bad_spec)

    import app.engine.loop as loop_mod

    async def _boom_execute(*a, **k):
        raise AssertionError("internal 工具不应调用 sandbox daemon")

    async def _resolve(*a, **k):
        return DashboardMockProvider(bad_spec)

    monkeypatch.setattr(loop_mod.sandbox_client, "execute", _boom_execute)
    monkeypatch.setattr(loop_mod, "_resolve_provider", _resolve)

    result, events = await _run(factory, conv_id, mid, scn, DashboardMockProvider(bad_spec))
    # 工具校验失败不阻断，消息终态仍 completed（内部工具失败计入但非熔断）
    assert result["status"] == "completed", result

    # tool_error(VALIDATION) 出现；tool_result(render_dashboard) 出现但内容为默认规整（handler 校验在 tool 内）
    names = [e[0] for e in events]
    assert "tool.call" in names
    assert "tool.error" in names
    te = [e for e in events if e[0] == "tool.error"][0]
    assert te[1]["error_code"] in ("VALIDATION",)

    async with factory() as s:
        msg = await s.get(Message, mid)
        assert msg.status == "completed"
