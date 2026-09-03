"""T32 follow-up 建议单测：done 后轻量 LLM 调用生成 3 条建议。

断言：SSE 收到 follow_up.suggestions（恰 3 条、id 连续、文本固定）；不落库
（message_events 无 follow_up 类型）；生成失败/非 JSON 静默降级（无事件、
消息终态仍 completed）。

注：测试环境 .env 配置了真实 LLM（seed 会注册 env-default），本文件将
get_default_provider 强制置 None 走 MockProvider 降级路径，保证确定性且
不发起外部调用。
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.engine.flow import ActiveFlowRegistry
from app.engine.loop import RunContext, run_flow
from app.llm import service as llm_service
from app.llm.mock_provider import MockProvider
from app.models import Conversation, Message, MessageEvent, User
from app.sse.hub import Hub, SSEStreamer
from app.tools.scenario import get_scenario

MOCK_SUGGESTIONS = ["查看本月销售额", "预测下季度销量趋势", "对比上周各区域销量"]


async def _prepare_env(factory) -> tuple[str, str, object]:
    """建用户/会话 + 助手消息占位，返回 (conversation_id, assistant_message_id, scenario)。"""
    async with factory() as s:
        user = User(email=f"fu-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="FU")
        s.add(user)
        await s.flush()
        conv = Conversation(owner_id=user.id, title="followup")
        s.add(conv)
        await s.flush()
        scn = await get_scenario(s)
        amsg = Message(
            conversation_id=conv.id, role="assistant", content="", status="running",
            trace_id=str(uuid.uuid4()),
        )
        s.add(amsg)
        await s.commit()
        await s.refresh(conv)
        await s.refresh(amsg)
        await s.refresh(scn)
        return str(conv.id), str(amsg.id), scn


async def _no_provider(session):  # noqa: ARG001
    return None


def _drain(streamer: SSEStreamer) -> list[tuple[str, dict, int | None]]:
    events = []
    while True:
        try:
            events.append(streamer.queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return events


async def _run_flow(factory, conv_id: str, mid: str, scn: object) -> list[tuple[str, dict, int | None]]:
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
            scenario=scn, user_id="fu@corp.com", flow=flow, hub=hub,
            session_factory=factory,
        )
        result = await run_flow(rctx, "你好，介绍一下你能做什么", factory)
        assert result["status"] == "completed", result
        return _drain(streamer)
    finally:
        await registry.release(conv_id)


@pytest.mark.asyncio
async def test_followup_published_on_completed(db_session_factory, monkeypatch):
    monkeypatch.setattr(llm_service, "get_default_provider", _no_provider)
    factory = db_session_factory
    conv_id, mid, _scn = await _prepare_env(factory)
    events = await _run_flow(factory, conv_id, mid, _scn)

    names = [e[0] for e in events]
    assert "done" in names
    assert "follow_up.suggestions" in names
    fu_events = [e for e in events if e[0] == "follow_up.suggestions"]
    assert len(fu_events) == 1
    payload = fu_events[0][1]
    assert payload["message_id"] == mid
    assert len(payload["suggestions"]) == 3
    assert [s["id"] for s in payload["suggestions"]] == ["1", "2", "3"]
    assert [s["text"] for s in payload["suggestions"]] == MOCK_SUGGESTIONS

    # 不落库：message_events 无 follow_up 相关类型
    async with factory() as s:
        evts = (await s.execute(select(MessageEvent).where(MessageEvent.message_id == mid))).scalars().all()
        assert evts, "事件链应有记录"
        assert all("follow_up" not in e.type for e in evts)


@pytest.mark.asyncio
async def test_followup_failure_silent(db_session_factory, monkeypatch):
    monkeypatch.setattr(llm_service, "get_default_provider", _no_provider)

    async def _boom(self, messages, config=None):  # noqa: ARG001
        raise RuntimeError("llm down")

    monkeypatch.setattr(MockProvider, "complete", _boom)

    factory = db_session_factory
    conv_id, mid, _scn = await _prepare_env(factory)
    events = await _run_flow(factory, conv_id, mid, _scn)

    names = [e[0] for e in events]
    assert "done" in names
    assert "follow_up.suggestions" not in names  # 失败 → 不发建议事件
    assert "error" not in names  # 且不破坏主流程

    async with factory() as s:
        msg = await s.get(Message, mid)
        assert msg.status == "completed"


@pytest.mark.asyncio
async def test_followup_non_json_silent(db_session_factory, monkeypatch):
    monkeypatch.setattr(llm_service, "get_default_provider", _no_provider)

    async def _garbage(self, messages, config=None):  # noqa: ARG001
        return "抱歉，我无法生成建议。"

    monkeypatch.setattr(MockProvider, "complete", _garbage)

    factory = db_session_factory
    conv_id, mid, _scn = await _prepare_env(factory)
    events = await _run_flow(factory, conv_id, mid, _scn)

    names = [e[0] for e in events]
    assert "done" in names
    assert "follow_up.suggestions" not in names
    async with factory() as s:
        msg = await s.get(Message, mid)
        assert msg.status == "completed"
