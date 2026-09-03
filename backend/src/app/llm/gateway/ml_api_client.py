"""Real blocking/streaming client for the ML Agent Chat gateway."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.config import get_settings


@dataclass
class AgentChatResult:
    answer: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)
    structured: Optional[dict[str, Any]] = None
    latency_ms: int = 0
    process_steps: list[str] = field(default_factory=list)


def build_inputs(
    message: str = "",
    params: Any = None,
    *,
    query: Optional[str] = None,
    conversation_id: Optional[str] = None,
    dialogue_count: int = 1,
    stream: bool = False,
    files: Optional[list[Any]] = None,
    oa: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    """Build safe gateway inputs; backend JWTs never enter this mapping."""
    _ = message, params, query, files
    settings = get_settings()
    result: dict[str, Any] = {}
    token = (access_token or "").strip()
    if token:
        result["new_token"] = token
    thinking = (settings.agent_enable_thinking or "").strip()
    if thinking:
        result["enableThinking"] = thinking
    attachment = (settings.agent_attachment or "").strip()
    if attachment:
        result["attachment"] = attachment
    resolved_oa = (oa or settings.agent_oa or "").strip()
    if resolved_oa:
        result["oa"] = resolved_oa
    result["dialogue_count"] = max(1, int(dialogue_count or 1))
    result["RESPONSE_STREAM_MODE"] = "True" if stream else "False"
    if conversation_id:
        result["conversation_id"] = conversation_id

    extra = (settings.agent_extra_inputs_json or "").strip()
    if extra:
        try:
            values = json.loads(extra)
        except json.JSONDecodeError:
            values = {}
        if isinstance(values, dict):
            for key, value in values.items():
                clean_key = str(key)
                if clean_key.startswith("sys."):
                    clean_key = clean_key[4:]
                # Do not allow a configured extra field to smuggle credentials or
                # duplicate fields owned by the request envelope.
                if clean_key.lower() in {"token", "jwt_token", "new_token", "authorization", "query", "files"}:
                    continue
                result[clean_key] = value
    return result


def _event_text(event: dict[str, Any]) -> str:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    event_type = str(event.get("event") or "")
    if event_type == "node_started":
        return f"进入节点：{data.get('title') or data.get('node_type') or data.get('node_id') or '节点'}"
    if event_type == "node_finished":
        return f"完成节点：{data.get('title') or data.get('node_type') or '节点'}"
    if event_type == "agent_thought":
        thought = str(event.get("thought") or data.get("thought") or "").strip()
        return "思考：" + (thought[:280] + ("…" if len(thought) > 280 else "") if thought else "分析中…")
    if event_type in {"agent_message", "message"}:
        return "正在生成最终答复…"
    if event_type == "message_end":
        return "回复生成完成，正在整理结果…"
    if event_type == "error":
        return "上游返回错误"
    return f"处理事件：{event_type}" if event_type else ""


def _event_answer(event: dict[str, Any]) -> str:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    for key in ("answer", "text", "content"):
        if event.get(key) is not None:
            return str(event.get(key) or "")
        if data.get(key) is not None:
            return str(data.get(key) or "")
    return ""


class MLApiClient:
    """The gateway client deliberately has no intent/planner/tool loop."""

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings or get_settings()

    @property
    def url(self) -> str:
        return self.settings.agent_api_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        key = (self.settings.agent_api_key or "").strip()
        if not key:
            raise RuntimeError("AGENT_API_KEY missing")
        authorization = key if key.lower().startswith("bearer ") else f"Bearer {key}"
        return {"Authorization": authorization, "Content-Type": "application/json"}

    def _timeout(self) -> float:
        return float(self.settings.agent_timeout_sec or 120.0)

    def _payload(self, *, query: str, inputs: dict[str, Any], user: str, conversation_id: Optional[str], files: Optional[list[dict[str, Any]]], mode: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "inputs": inputs if inputs is not None else {},
            "query": query,
            "response_mode": mode,
            "user": user,
            "files": files or [],
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return payload

    async def health(self) -> dict[str, Any]:
        configured = bool((self.settings.agent_api_key or "").strip())
        response: dict[str, Any] = {
            "ok": configured,
            "mode": "live" if configured else "disabled",
            "configured_mode": self.settings.agent_response_mode or "blocking",
            "url": self.url,
            "provider": "ml-api-gateway",
        }
        if not configured:
            response["error"] = "AGENT_API_KEY missing"
        return response

    async def chat(
        self,
        query: str,
        inputs: dict[str, Any],
        user: str,
        conversation_id: Optional[str] = None,
        files: Optional[list[dict[str, Any]]] = None,
    ) -> AgentChatResult:
        if (self.settings.agent_response_mode or "blocking").lower() == "streaming":
            steps: list[str] = []
            async for item in self.stream_chat(query, inputs, user, conversation_id, files):
                if item.get("type") == "status" and item.get("text"):
                    steps.append(str(item["text"]))
                if item.get("type") == "result":
                    result = item["result"]
                    result.process_steps = steps
                    return result
            raise RuntimeError("stream ended without final answer")

        payload = self._payload(query=query, inputs=inputs, user=user, conversation_id=conversation_id, files=files, mode="blocking")
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout(), trust_env=False) as client:
                response = await client.post(self.url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError("ML gateway request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("ML gateway request failed") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"ML gateway HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("ML gateway returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("ML gateway returned invalid JSON")
        answer = str(data.get("answer") or data.get("text") or (data.get("data") or {}).get("answer") or "")
        if not answer:
            raise RuntimeError("ML gateway response missing answer")
        return AgentChatResult(
            answer=answer,
            conversation_id=data.get("conversation_id") or data.get("conversationId") or conversation_id,
            message_id=data.get("message_id") or data.get("messageId") or data.get("id"),
            raw=data,
            structured=data.get("structured") if isinstance(data.get("structured"), dict) else None,
            latency_ms=int((time.perf_counter() - start) * 1000),
            process_steps=["已收到 Agent 阻塞响应，正在整理结果…"],
        )

    async def stream_chat(
        self,
        query: str,
        inputs: dict[str, Any],
        user: str,
        conversation_id: Optional[str] = None,
        files: Optional[list[dict[str, Any]]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = self._payload(query=query, inputs=inputs, user=user, conversation_id=conversation_id, files=files, mode="streaming")
        start = time.perf_counter()
        answer_parts: list[str] = []
        raw_events: list[dict[str, Any]] = []
        conv_id = conversation_id
        message_id: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=self._timeout(), trust_env=False) as client:
                async with client.stream("POST", self.url, headers=self._headers(), json=payload) as response:
                    if response.status_code >= 400:
                        raise RuntimeError(f"ML gateway HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line or line.startswith("event:") or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        if raw == "[DONE]":
                            break
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        event_type = str(event.get("event") or "")
                        if event_type in {"ping", "ping_event"}:
                            continue
                        raw_events.append(event)
                        conv_id = event.get("conversation_id") or event.get("conversationId") or conv_id
                        message_id = event.get("message_id") or event.get("messageId") or event.get("id") or message_id
                        text = _event_text(event)
                        if event_type in {"agent_thought", "node_started", "node_finished", "agent_message", "message_end", "error"}:
                            yield {"type": "status", "status": event_type, "event": event_type, "text": text, "data": event.get("data")}
                        if event_type in {"agent_message", "message"}:
                            answer_parts.append(_event_answer(event))
                        if event_type == "error":
                            raise RuntimeError("ML gateway stream returned an error")
        except httpx.TimeoutException as exc:
            raise RuntimeError("ML gateway stream timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("ML gateway stream failed") from exc
        answer = "".join(answer_parts)
        if not answer:
            for event in reversed(raw_events):
                answer = _event_answer(event)
                if answer:
                    break
        if not answer:
            raise RuntimeError("ML gateway stream ended without final answer")
        yield {"type": "result", "result": AgentChatResult(answer=answer, conversation_id=conv_id, message_id=message_id, raw={"events": raw_events}, latency_ms=int((time.perf_counter() - start) * 1000))}


AgentChatClient = MLApiClient
LiveChatClient = MLApiClient
