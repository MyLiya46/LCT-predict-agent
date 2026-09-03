"""Small, side-effect-free parser for the ML gateway result envelope."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Intent = Literal["history", "forecast", "attribution", "whatif"]


class Metric(BaseModel):
    label: str
    value: str
    unit: str = ""


class TextBlock(BaseModel):
    title: str = "分析解读"
    markdown: str = ""
    metrics: list[Metric] = Field(default_factory=list)


class TableColumn(BaseModel):
    key: str
    title: str
    align: Literal["left", "right", "center"] = "left"


class TableBlock(BaseModel):
    columns: list[TableColumn]
    rows: list[dict[str, Any]]


class ChartBlock(BaseModel):
    type: Literal["line_band", "bar", "line", "pie", "waterfall"]
    option: dict[str, Any]


class ResultMeta(BaseModel):
    tool: str = "chat-messages"
    latency_ms: int = 0
    cached: bool = False
    task_id: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[str] = None
    output_path: Optional[str] = None
    system_forecast_number: Optional[str] = None
    workbench_synced: Optional[bool] = None


class AgentResultEnvelope(BaseModel):
    intent: Intent
    text: TextBlock
    chart: Optional[ChartBlock] = None
    table: Optional[TableBlock] = None
    meta: Optional[ResultMeta] = None
    follow_ups: list[str] = Field(default_factory=list)
    update_workspace: bool = True
    process_steps: list[str] = Field(default_factory=list)


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_INTENTS = {"history", "forecast", "attribution", "whatif"}


def extract_json_payload(text: str) -> Optional[dict[str, Any]]:
    """Extract one JSON object from a plain answer or a fenced/prose answer."""
    if not text:
        return None
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    candidates.extend(match.group(1).strip() for match in _JSON_FENCE.finditer(text))
    # A gateway sometimes prefixes a valid object with a short explanation.
    candidates.extend(text[index:] for index, char in enumerate(text) if char == "{")
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _intent(value: Any, fallback: str) -> Intent:
    candidate = str(value or fallback).strip().lower()
    return candidate if candidate in _INTENTS else (fallback if fallback in _INTENTS else "history")  # type: ignore[return-value]


def infer_intent_from_payload(payload: dict[str, Any], fallback: str) -> Intent:
    if "factors" in payload:
        return "attribution"
    if "baseline" in payload and "scenario" in payload:
        return "whatif"
    if "forecast" in payload or "forecast_points" in payload:
        return "forecast"
    if "series" in payload or "product" in payload:
        return "history"
    return _intent(payload.get("intent"), fallback)


def _metrics(value: Any) -> list[Metric]:
    if not isinstance(value, list):
        return []
    result: list[Metric] = []
    for item in value[:6]:
        if not isinstance(item, dict) or item.get("label") is None:
            continue
        result.append(Metric(label=str(item["label"]), value=str(item.get("value", "")), unit=str(item.get("unit", ""))))
    return result


def _chart(value: Any) -> Optional[ChartBlock]:
    if not isinstance(value, dict) or value.get("type") not in {"line_band", "bar", "line", "pie", "waterfall"}:
        return None
    option = value.get("option")
    return ChartBlock(type=value["type"], option=option) if isinstance(option, dict) else None


def _table(value: Any) -> Optional[TableBlock]:
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        return None
    columns = value.get("columns")
    if not isinstance(columns, list):
        rows = value["rows"]
        keys = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        columns = [{"key": key, "title": key} for key in keys]
    try:
        return TableBlock(columns=columns, rows=[row for row in value["rows"] if isinstance(row, dict)])
    except (TypeError, ValueError):
        return None


def _meta(value: Any, *, tool_label: str, latency_ms: int) -> ResultMeta:
    raw = value if isinstance(value, dict) else {}
    allowed = {key: raw[key] for key in ResultMeta.model_fields if key in raw}
    allowed.setdefault("tool", tool_label)
    allowed.setdefault("latency_ms", latency_ms)
    try:
        return ResultMeta.model_validate(allowed)
    except (TypeError, ValueError):
        return ResultMeta(tool=tool_label, latency_ms=latency_ms)


def envelope_from_chat_answer(
    *,
    answer: str,
    intent: str,
    latency_ms: int = 0,
    tool_label: str = "chat-messages",
    structured: Optional[dict[str, Any]] = None,
) -> AgentResultEnvelope:
    """Convert upstream text/structured data without selecting a capability."""
    payload = structured if isinstance(structured, dict) else extract_json_payload(answer)
    if payload:
        resolved = infer_intent_from_payload(payload, intent)
        text_raw = payload.get("text") if isinstance(payload.get("text"), dict) else {}
        markdown = str(
            text_raw.get("markdown")
            or payload.get("markdown")
            or payload.get("summary")
            or payload.get("answer")
            or answer
            or "_（空响应）_"
        )
        title = str(text_raw.get("title") or payload.get("title") or "分析解读")
        follow_ups = payload.get("follow_ups") or payload.get("related_questions") or []
        return AgentResultEnvelope(
            intent=resolved,
            text=TextBlock(title=title, markdown=markdown, metrics=_metrics(text_raw.get("metrics") or payload.get("metrics"))),
            chart=_chart(payload.get("chart")),
            table=_table(payload.get("table")),
            meta=_meta(payload.get("meta"), tool_label=tool_label, latency_ms=latency_ms),
            follow_ups=[str(item) for item in follow_ups[:3]] if isinstance(follow_ups, list) else [],
            update_workspace=bool(payload.get("update_workspace", True)),
            process_steps=[str(item) for item in payload.get("process_steps", [])[:20]] if isinstance(payload.get("process_steps"), list) else [],
        )
    return AgentResultEnvelope(
        intent=_intent(intent, "history"),
        text=TextBlock(title="分析解读", markdown=answer or "_（空响应）_", metrics=[]),
        meta=ResultMeta(tool=tool_label, latency_ms=max(0, int(latency_ms))),
    )
