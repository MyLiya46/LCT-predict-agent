"""OpenAI 协议兼容适配器（T09 / tech_design §3.8）。

POST {base_url}/chat/completions（stream=true），解析 SSE 数据行：
- delta.content → ContentDeltaEvent
- delta.tool_calls → 按 index/id/name/arguments 增量聚合 → ToolCallBatchEvent
- finish_reason → DoneReasonEvent
- 网络/HTTP 错误 → ErrorEvent（retry 语义归引擎侧）
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from app.llm.events import (
    ContentDeltaEvent,
    DoneReasonEvent,
    ErrorEvent,
    ProviderUnavailable,
    StreamEvent,
    ToolCall,
    ToolCallBatchEvent,
)

CONNECT_TIMEOUT_S = 5
FIRST_BYTE_TIMEOUT_S = 30
TOTAL_TIMEOUT_S = 180


class OpenAICompatProvider:
    """OpenAI 协议兼容 provider。"""

    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        base_url: str,
        api_key: str,
        default_model: str = "",
        status: str = "healthy",
    ) -> None:
        self.provider_id = provider_id
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.status = status

    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        config = config or {}
        model = config.get("model") or self.default_model or "default"
        total_timeout = config.get("total_timeout", TOTAL_TIMEOUT_S)

        payload: dict[str, Any] = {
            "model": model,
            "messages": _normalize_messages(messages),
            "stream": True,
        }
        if tools:
            payload["tools"] = _normalize_tools(tools)

        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"

        timeout = httpx.Timeout(total_timeout, connect=CONNECT_TIMEOUT_S, read=FIRST_BYTE_TIMEOUT_S)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        err_text = (await resp.aread()).decode("utf-8", errors="ignore")[:500]
                        code = "UPSTREAM" if resp.status_code >= 500 else "UPSTREAM"
                        yield ErrorEvent(code=code, message=f"HTTP {resp.status_code}: {err_text}")
                        return

                    tool_builder: dict[int, dict[str, Any]] = {}
                    text_buffer: list[str] = []
                    stop_reason = ""
                    usage: Optional[dict[str, int]] = None
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:  # noqa: PERF203
                            continue

                        # T38：累计 usage（末 chunk 常规携带；以最后一次非空为准）
                        if chunk.get("usage"):
                            u = chunk["usage"]
                            usage = {
                                "prompt_tokens": int(u.get("prompt_tokens") or 0),
                                "completion_tokens": int(u.get("completion_tokens") or 0),
                            }

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        finish = choice.get("finish_reason")
                        if finish:
                            # OpenAI finish_reason=tool_calls → 引擎约定 tool_use（附录 A / events.py）
                            stop_reason = "tool_use" if finish in ("tool_calls", "function_call") else finish

                        # 1) 文本增量
                        content = delta.get("content")
                        if content:
                            text_buffer.append(content)
                            yield ContentDeltaEvent(text=content)

                        # 2) 工具调用增量（分段聚合）
                        tc = delta.get("tool_calls")
                        if tc:
                            for item in tc:
                                idx = item.get("index", 0)
                                slot = tool_builder.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if item.get("id"):
                                    slot["id"] = item["id"]
                                fn = item.get("function") or {}
                                if fn.get("name"):
                                    slot["name"] = fn["name"]
                                if fn.get("arguments"):
                                    slot["arguments"] += fn["arguments"]

                    # 3) 工具调用 batch（若 stop_reason=tool_use 或存在聚合）
                    if tool_builder:
                        calls = []
                        for idx in sorted(tool_builder):
                            slot = tool_builder[idx]
                            args: dict[str, Any] = {}
                            if slot.get("arguments"):
                                try:
                                    args = json.loads(slot["arguments"])
                                except json.JSONDecodeError:
                                    args = {"__raw__": slot["arguments"]}
                            calls.append(
                                ToolCall(
                                    index=idx,
                                    id=slot.get("id") or f"call_{idx}",
                                    name=slot.get("name") or "",
                                    arguments=args,
                                )
                            )
                        if calls:
                            yield ToolCallBatchEvent(calls=calls)

                    final_text = "".join(text_buffer)
                    yield DoneReasonEvent(
                        stop_reason=stop_reason or ("tool_use" if tool_builder else "stop"),
                        final_text=final_text,
                        usage=usage,
                    )
        except httpx.TimeoutException as exc:
            yield ErrorEvent(code="TIMEOUT", message=f"LLM 调用超时: {exc}")
        except httpx.HTTPError as exc:
            yield ErrorEvent(code="UPSTREAM", message=f"LLM 上游错误: {exc}")

    # ------------------------------------------------------------------
    async def complete(
        self,
        messages: list[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
    ) -> str:
        """T32：一次性非流式补全（stream=false），返回 choices[0].message.content。

        短超时（默认 10s）；HTTP/网络错误 → ProviderUnavailable（引擎侧静默降级）。
        """
        config = config or {}
        model = config.get("model") or self.default_model or "default"
        total_timeout = config.get("total_timeout", 10.0)
        payload: dict[str, Any] = {
            "model": model,
            "messages": _normalize_messages(messages),
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"
        timeout = httpx.Timeout(total_timeout, connect=CONNECT_TIMEOUT_S, read=FIRST_BYTE_TIMEOUT_S)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"LLM 补全调用失败: {exc}", provider_id=self.provider_id) from exc
        if resp.status_code != 200:
            err_text = resp.text[:300]
            raise ProviderUnavailable(
                f"LLM 补全 HTTP {resp.status_code}: {err_text}", provider_id=self.provider_id
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content") or ""

    # ------------------------------------------------------------------
    async def check_health(self) -> bool:
        """GET {base_url}/models（Bearer api_key）→ 200 即 healthy。"""
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(url, headers=headers)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """消息归一：保证 role/content/name 合法，去掉非 OpenAI 字段。"""
    out = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant", "system", "tool"):
            role = "user"
        item: dict[str, Any] = {"role": role, "content": m.get("content") or ""}
        if role in ("assistant",) and m.get("tool_calls"):
            item["tool_calls"] = m["tool_calls"]
        if role == "tool" and m.get("tool_call_id"):
            item["tool_call_id"] = m["tool_call_id"]
        out.append(item)
    return out


def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI tools 协议（type=function, function:{name,description,parameters}）。"""
    out = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return out
