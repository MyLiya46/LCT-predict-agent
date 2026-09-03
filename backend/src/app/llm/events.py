"""统一 LLM 事件模型（T09 / tech_design §3.8）。

StreamEvent = ContentDeltaEvent | ToolCallBatchEvent | DoneReasonEvent | ErrorEvent
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class ToolCall:
    index: int
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentDeltaEvent:
    type: Literal["content_delta"] = "content_delta"
    text: str = ""


@dataclass
class ToolCallBatchEvent:
    type: Literal["tool_call.batch"] = "tool_call.batch"
    calls: list[ToolCall] = field(default_factory=list)


@dataclass
class DoneReasonEvent:
    type: Literal["done_reason"] = "done_reason"
    stop_reason: str = "stop"  # stop | tool_use | length
    final_text: str = ""
    #: T38：流式末 chunk 携带的 token 用量（可选；无则 None）
    usage: Optional[dict[str, int]] = None


@dataclass
class ErrorEvent:
    type: Literal["error"] = "error"
    code: str = "UPSTREAM"  # TIMEOUT | UPSTREAM | 5xx
    message: str = ""


StreamEvent = ContentDeltaEvent | ToolCallBatchEvent | DoneReasonEvent | ErrorEvent


class ProviderUnavailable(Exception):
    """供应商不可用（unhealthy 或调用前探测失败）信号，引擎可降级。"""

    def __init__(self, message: str = "LLM 供应商不可用", provider_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.provider_id = provider_id
