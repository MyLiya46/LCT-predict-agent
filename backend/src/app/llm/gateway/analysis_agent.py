"""Optional Turing report/attribution enrichment with safe base fallback."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.config import get_settings
from app.llm.gateway import turing
from app.llm.gateway.response_parser import (
    AgentResultEnvelope,
    TextBlock,
    _chart,
    _metrics,
    _table,
    extract_json_payload,
)
from app.llm.gateway.result_utils import strip_related_suggestions

turing_client = turing


def analysis_agent_enabled() -> bool:
    return bool(get_settings().analysis_agent_enabled) and turing.turing_configured()


def _analysis_payload(raw: str) -> Optional[dict[str, Any]]:
    payload = extract_json_payload(raw)
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    if not isinstance(text, dict):
        # Accept the compact equivalent, but require actual analysis text.
        if isinstance(payload.get("markdown"), str):
            text = {"markdown": payload["markdown"], "title": payload.get("title")}
        else:
            return None
    markdown = text.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return None
    return {**payload, "text": text}


def _merge(base: AgentResultEnvelope, payload: dict[str, Any]) -> AgentResultEnvelope:
    result = base.model_copy(deep=True)
    text = payload["text"]
    result.text = TextBlock(
        title=str(text.get("title") or "分析解读"),
        markdown=strip_related_suggestions(str(text["markdown"])),
        metrics=_metrics(text.get("metrics")),
    )
    if "chart" in payload:
        result.chart = _chart(payload.get("chart"))
    if "table" in payload:
        result.table = _table(payload.get("table"))
    if isinstance(payload.get("follow_ups"), list):
        result.follow_ups = [str(item) for item in payload["follow_ups"][:3]]
    return result


async def enrich_envelope(
    *,
    user_query: str,
    core_answer: str,
    intent: str,
    structured: Optional[dict[str, Any]],
    base_envelope: AgentResultEnvelope,
    core_latency_ms: int = 0,
) -> AgentResultEnvelope:
    """Enhance a parsed envelope; every unavailable/invalid path returns base."""
    _ = core_latency_ms
    settings = get_settings()
    if not settings.analysis_agent_enabled or not turing.turing_configured():
        return base_envelope
    prompt = {
        "user_query": user_query,
        "intent": intent,
        "core_agent_answer": (core_answer or "")[:12000],
        "structured_payload": structured,
        "base_envelope": base_envelope.model_dump(mode="json"),
    }
    messages = [
        {"role": "system", "content": "只输出一个 JSON 对象，包含 text.markdown，可选 chart/table/text.metrics。不要添加追问。"},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, default=str)},
    ]
    try:
        raw = await turing.chat_completion(messages=messages, temperature=0.2, response_format={"type": "json_object"})
    except Exception:  # noqa: BLE001
        return base_envelope
    payload = _analysis_payload(raw)
    if payload is None:
        return base_envelope
    try:
        return _merge(base_envelope, payload)
    except (TypeError, ValueError):
        return base_envelope
