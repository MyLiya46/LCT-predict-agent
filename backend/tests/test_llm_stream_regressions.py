"""流式 Provider 回归：兼容无空格 data 行并保持工具调用完整。"""

import json

import httpx
import pytest
import respx

from app.llm.adapter_openai import OpenAICompatProvider
from app.llm.events import ContentDeltaEvent, DoneReasonEvent, ToolCallBatchEvent


@pytest.mark.asyncio
@respx.mock
async def test_openai_stream_accepts_data_without_optional_space():
    rows = [
        {"choices": [{"delta": {"content": "流式"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "输出"}, "finish_reason": "stop"}]},
    ]
    sse = "\r\n".join([*(f"data:{json.dumps(row, ensure_ascii=False)}\r\n" for row in rows), "data:[DONE]\r\n"])
    respx.post("http://llm-regression.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    provider = OpenAICompatProvider(
        provider_id="p-stream", name="regression", base_url="http://llm-regression.test/v1", api_key="secret", default_model="m"
    )

    events = [event async for event in provider.chat([{"role": "user", "content": "q"}])]
    assert "".join(event.text for event in events if isinstance(event, ContentDeltaEvent)) == "流式输出"
    done = next(event for event in events if isinstance(event, DoneReasonEvent))
    assert done.stop_reason == "stop"


@pytest.mark.asyncio
@respx.mock
async def test_openai_stream_keeps_fragmented_tool_arguments_and_redacts_http_body():
    rows = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "echo", "arguments": '{"x":"'}}]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'secret"}'}}]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    sse = "\n".join([*(f"data:{json.dumps(row, ensure_ascii=False)}" for row in rows), "data:[DONE]"])
    respx.post("http://llm-regression.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    provider = OpenAICompatProvider(
        provider_id="p-tool", name="regression", base_url="http://llm-regression.test/v1", api_key="secret", default_model="m"
    )
    events = [event async for event in provider.chat([{"role": "user", "content": "q"}])]
    tool_event = next(event for event in events if isinstance(event, ToolCallBatchEvent))
    assert tool_event.calls[0].arguments == {"x": "secret"}

    respx.reset()
    respx.post("http://llm-regression.test/v1/chat/completions").mock(
        return_value=httpx.Response(502, text="upstream secret")
    )
    errors = [event async for event in provider.chat([{"role": "user", "content": "q"}])]
    assert "upstream secret" not in next(event for event in errors if event.type == "error").message
