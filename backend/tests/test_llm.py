"""T09 LLM 抽象层单测：OpenAI 兼容流解析（content/tool_calls/finish_reason）、健康检查。"""

import json

import httpx
import pytest
import respx

from app.llm.adapter_openai import OpenAICompatProvider
from app.llm.events import ContentDeltaEvent, DoneReasonEvent, ToolCallBatchEvent


def _sse_lines(rows: list[dict]) -> str:
    out = []
    for row in rows:
        out.append(f"data: {json.dumps(row, ensure_ascii=False)}")
        out.append("")
    out.append("data: [DONE]")
    return "\n".join(out)


@pytest.mark.asyncio
@respx.mock
async def test_stream_normalize_content_and_tool_calls():
    payload = _sse_lines(
        [
            {"choices": [{"delta": {"content": "你好"}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "query_sales_data", "arguments": '{"dim'}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ensions": ["region"]}'}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_use"}]},
        ]
    )
    respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=payload, headers={"Content-Type": "text/event-stream"})
    )
    provider = OpenAICompatProvider(
        provider_id="p1", name="t", base_url="http://llm.test/v1", api_key="k", default_model="m"
    )
    events = []
    async for evt in provider.chat([{"role": "user", "content": "hi"}], tools=[]):
        events.append(evt)

    # content delta → tool_call.batch（参数聚合）→ done_reason(tool_use)
    types = [type(e).__name__ for e in events]
    assert any(isinstance(e, ContentDeltaEvent) for e in events)
    tool_evt = next(e for e in events if isinstance(e, ToolCallBatchEvent))
    assert tool_evt.calls[0].name == "query_sales_data"
    assert tool_evt.calls[0].arguments == {"dimensions": ["region"]}
    done = next(e for e in events if isinstance(e, DoneReasonEvent))
    assert done.stop_reason == "tool_use"


@pytest.mark.asyncio
@respx.mock
async def test_stop_reason_no_tool_calls():
    payload = _sse_lines([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}])
    respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=payload, headers={"Content-Type": "text/event-stream"})
    )
    provider = OpenAICompatProvider(provider_id="p2", name="t", base_url="http://llm.test/v1", api_key="k", default_model="m")
    events = []
    async for evt in provider.chat([{"role": "user", "content": "hi"}]):
        events.append(evt)
    done = next(e for e in events if isinstance(e, DoneReasonEvent))
    assert done.stop_reason == "stop"
    assert not any(isinstance(e, ToolCallBatchEvent) for e in events)


@pytest.mark.asyncio
@respx.mock
async def test_5xx_becomes_upstream_error():
    respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(503, text="overloaded")
    )
    from app.llm.events import ErrorEvent

    provider = OpenAICompatProvider(provider_id="p3", name="t", base_url="http://llm.test/v1", api_key="k", default_model="m")
    events = []
    async for evt in provider.chat([{"role": "user", "content": "hi"}]):
        events.append(evt)
    err = next(e for e in events if isinstance(e, ErrorEvent))
    assert err.code in ("UPSTREAM", "TIMEOUT")


@pytest.mark.asyncio
@respx.mock
async def test_health_check():
    respx.get("http://llm.test/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    provider = OpenAICompatProvider(provider_id="p4", name="t", base_url="http://llm.test/v1", api_key="k", default_model="m")
    assert await provider.check_health() is True

    respx.get("http://llm.test/v1/models").mock(return_value=httpx.Response(500))
    assert await provider.check_health() is False