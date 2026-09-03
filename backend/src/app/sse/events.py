"""SSE 事件协议常量与载荷构造函数（tech_design §3.9 / 附录 A / T10）。

对外 SSE 事件名与 PRD §12.4 对齐统一后的五类 + done/error。
"""
from __future__ import annotations

import json
from typing import Any, Optional

# ------------------------------------------------------------------
# 事件名常量（对外 SSE wire 名）
# ------------------------------------------------------------------
EVT_MESSAGE_CREATED = "message.created"
EVT_MESSAGE_DELTA = "message.delta"
EVT_AGENT_STATUS = "agent.status"
EVT_AGENT_PROCESS = "agent.process"
EVT_TOOL_CALL = "tool.call"
EVT_TOOL_RESULT = "tool.result"
EVT_TOOL_ERROR = "tool.error"
EVT_DONE = "done"
EVT_ERROR = "error"
EVT_FOLLOW_UP = "follow_up.suggestions"  # T32：AI 回复完成后的 follow-up 建议（不落库，仅 SSE）

# T38：会话级事件流（Live Tail）SSE 事件
EVT_SESSION_META = "session.meta"
EVT_SESSION_PACK = "session.pack"

# `id:` 行用 seq（日志诊断）
SSE_PING_INTERVAL_S = 5

# ------------------------------------------------------------------
# 内部事件类型 → 对外 SSE wire 名（T38 会话级流回放映射，附录 C → 附录 A）
# sse_opened 为连接内部事件，不回放（历史上从不经 hub 发到 wire）。
# ------------------------------------------------------------------
INTERNAL_TO_WIRE: dict[str, str] = {
    "message_created": EVT_MESSAGE_CREATED,
    "agent_process": EVT_AGENT_PROCESS,
    "tool_call": EVT_TOOL_CALL,
    "tool_result": EVT_TOOL_RESULT,
    "tool_error": EVT_TOOL_ERROR,
    "done": EVT_DONE,
}


class SsePayload:
    """载荷构造函数（附录 A schema 逐字段）。"""

    @staticmethod
    def created(message_id: str) -> dict:
        return {"message_id": str(message_id)}

    @staticmethod
    def delta(text: str) -> dict:
        return {"text": text}

    @staticmethod
    def agent(state: str, detail: Optional[str] = None) -> dict:
        data: dict[str, Any] = {"state": state}
        if detail is not None:
            data["detail"] = detail
        return data

    @staticmethod
    def tool_call(name: str, input: Any, plan_index: int, request_id: str) -> dict:
        return {"name": name, "input": input, "plan_index": plan_index, "request_id": request_id}

    @staticmethod
    def tool_result(name: str, output_summary: Any, duration_ms: int, status: str) -> dict:
        return {
            "name": name,
            "output_summary": output_summary,
            "duration_ms": duration_ms,
            "status": status,
        }

    @staticmethod
    def tool_error(name: str, error_code: str, message: str, retried: int) -> dict:
        return {"name": name, "error_code": error_code, "message": message, "retried": retried}

    @staticmethod
    def done(message_id: str, final_text: str, status: str, usage: Optional[dict] = None) -> dict:
        data: dict[str, Any] = {"message_id": str(message_id), "final_text": final_text, "status": status}
        if usage is not None:
            data["usage"] = usage
        return data

    @staticmethod
    def session_meta(conversation_id: str, event_total: int, token_total: int) -> dict:
        """T38：会话级流元信息（连接后发，事件总数 + 累计 token）。"""
        return {
            "conversation_id": str(conversation_id),
            "event_total": event_total,
            "token_total": token_total,
        }

    @staticmethod
    def session_pack(event_type: str, payload: dict, seq: int, turn_index: int, ts: str) -> dict:
        """T38：会话级流事件包装（event_type + 原载荷 + 定位/时间）。"""
        return {
            "event_type": event_type,
            "payload": payload,
            "seq": seq,
            "turn_index": turn_index,
            "ts": ts,
        }

    @staticmethod
    def error(code: str, message: str) -> dict:
        return {"code": code, "message": message}

    @staticmethod
    def follow_up(message_id: str, suggestions: list[dict]) -> dict:
        """T32：follow-up 建议载荷（suggestions: [{"id": "1", "text": "..."}]）。"""
        return {"message_id": str(message_id), "suggestions": suggestions}


def sse_frame(event: str, data: dict, seq: Optional[int] = None) -> str:
    """序列化 SSE 帧：`id:`/`event:`/`data:` 行 + 空行（json.dumps 单行）。"""
    lines = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"
