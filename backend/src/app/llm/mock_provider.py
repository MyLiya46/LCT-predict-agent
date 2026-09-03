"""MockProvider：无真实 LLM 时的降级驱动（T09/T16 联调用）。

按 prompt 中是否包含「查询」「预测」等关键词返回脚本化回复；
供引擎测试与「外部依赖未真连」场景使用，不接入任何真实服务。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

from app.llm.events import ContentDeltaEvent, DoneReasonEvent, ToolCall, ToolCallBatchEvent

MOCK_USAGE = {"prompt_tokens": 120, "completion_tokens": 80}  # T38：mock 固定 usage


class MockProvider:
    """脚本化 mock：识别工具调用意图返回 batch。"""

    def __init__(self, name: str = "mock", default_model: str = "mock-model", base_url: str = "") -> None:
        self.name = name
        self.default_model = default_model
        self.base_url = base_url
        self.status = "healthy"
        self.provider_id = "mock-provider"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[Any]:
        """两轮脚本：先 tool_use（若 tools 含 query/predict），后 stop 文本。

        若上下文已含 tool 结果回灌（messages 中出现 role=tool）→ 直接 stop 汇总，
        避免脚本化 mock 死循环（模拟真实模型看结果后收尾）。
        """
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if has_tool_result:
            reply = "（mock）根据工具返回结果，已完成该请求的汇总分析。"
            for chunk in (reply[i : i + 6] for i in range(0, len(reply), 6)):
                yield ContentDeltaEvent(text=chunk)
                await asyncio.sleep(0)
            yield DoneReasonEvent(stop_reason="stop", final_text=reply, usage=dict(MOCK_USAGE))
            return

        text = "".join(str(m.get("content", "")) for m in messages)
        tool_names = [t.get("name", "") for t in (tools or [])]

        if "预测" in text and "predict_sales" in tool_names:
            args = {"model": "default", "horizon": 3, "base": {"region": "华东", "period": "近6月"}}
            yield ContentDeltaEvent(text="")
            yield ToolCallBatchEvent(calls=[ToolCall(index=0, id="call_mock_predict", name="predict_sales", arguments=args)])
            yield DoneReasonEvent(stop_reason="tool_use", final_text="")
            return

        if ("查询" in text or "销量" in text) and "query_sales_data" in tool_names:
            args = {"dimensions": ["region"], "time_range": {"start": "2026-02-01", "end": "2026-07-31"}, "filters": {}}
            yield ContentDeltaEvent(text="")
            yield ToolCallBatchEvent(calls=[ToolCall(index=0, id="call_mock_query", name="query_sales_data", arguments=args)])
            yield DoneReasonEvent(stop_reason="tool_use", final_text="")
            return

        # 直接文本回答
        reply = "（mock）已为你完成该请求的分析。"
        for chunk in (reply[i : i + 6] for i in range(0, len(reply), 6)):
            yield ContentDeltaEvent(text=chunk)
            await asyncio.sleep(0)
        yield DoneReasonEvent(stop_reason="stop", final_text=reply, usage=dict(MOCK_USAGE))

    async def complete(
        self,
        messages: list[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
    ) -> str:
        """T32：一次性补全（mock）——固定返回 3 条建议 JSON，模拟真实结构。"""
        return json.dumps(
            [
                {"id": "1", "text": "查看本月销售额"},
                {"id": "2", "text": "预测下季度销量趋势"},
                {"id": "3", "text": "对比上周各区域销量"},
            ],
            ensure_ascii=False,
        )

    async def check_health(self) -> bool:
        return True
