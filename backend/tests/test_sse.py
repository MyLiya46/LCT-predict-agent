"""T10 SSE hub 单测：双客户端广播、断连清理、载荷 schema（附录 A）。"""

import asyncio
import json

import pytest

from app.sse.events import (
    EVT_AGENT_PROCESS,
    EVT_DONE,
    EVT_MESSAGE_CREATED,
    EVT_MESSAGE_DELTA,
    EVT_TOOL_CALL,
    EVT_TOOL_ERROR,
    EVT_TOOL_RESULT,
    SsePayload,
    sse_frame,
)
from app.sse.hub import Hub, SSEStreamer


async def drain(streamer: SSEStreamer, n: int) -> list[str]:
    out: list[str] = []
    buf = streamer.queue
    for _ in range(n):
        event, data, seq = await asyncio.wait_for(buf.get(), timeout=1.0)
        out.append(sse_frame(event, data, seq))
    return out


@pytest.mark.asyncio
async def test_broadcast_two_clients():
    hub = Hub()
    cid = "conv-1"
    s1 = SSEStreamer(cid)
    s2 = SSEStreamer(cid)
    await hub.attach(cid, s1)
    await hub.attach(cid, s2)

    await hub.publish(cid, EVT_MESSAGE_CREATED, SsePayload.created("m-1"), seq=1)

    frames = await drain(s1, 1) + await drain(s2, 1)
    for frame in frames:
        assert "event: message.created" in frame
        assert '"message_id": "m-1"' in frame
        assert frame.startswith("id: 1")


@pytest.mark.asyncio
async def test_detach_on_stale():
    hub = Hub()
    cid = "conv-2"
    s = SSEStreamer(cid)
    await hub.attach(cid, s)
    # 手动模拟 stale：直接篡改最后活跃时间（用属性）
    import time as _t

    s._last_activity = _t.monotonic() - 60  # noqa: SLF001
    await hub.publish(cid, EVT_DONE, SsePayload.done("m-2", "final", "completed"))
    assert len(hub._clients.get(cid, ())) == 0  # noqa: SLF001


def test_payload_schema():
    p = SsePayload.tool_call("query_sales_data", {"region": "华东"}, 0, "req-1")
    assert p == {"name": "query_sales_data", "input": {"region": "华东"}, "plan_index": 0, "request_id": "req-1"}

    p = SsePayload.tool_error("predict_sales", "UPSTREAM", "上游 5xx", retried=2)
    assert set(p) == {"name", "error_code", "message", "retried"}

    p = SsePayload.agent("retrying", detail="重试 2/3")
    assert p["state"] == "retrying"


def test_load_all_event_names_consistent():
    names = {
        EVT_MESSAGE_CREATED, EVT_MESSAGE_DELTA, EVT_AGENT_PROCESS,
        EVT_TOOL_CALL, EVT_TOOL_RESULT, EVT_TOOL_ERROR, EVT_DONE,
    }
    expected = {
        "message.created", "message.delta", "agent.process",
        "tool.call", "tool.result", "tool.error", "done",
    }
    assert names == expected