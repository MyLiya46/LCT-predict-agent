"""Normalize native capability output into the frontend workbench envelope.

The native engine owns capability selection.  This module only projects the
last successful ``response_type`` and its structured output; it does not
inspect intent/planner fields or perform another classification pass.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

RESPONSE_TYPES = frozenset(
    {"history", "forecast", "attribution", "report", "simulation", "optimization"}
)
_INTENT_BY_TYPE = {
    "history": "history",
    "forecast": "forecast",
    "attribution": "attribution",
    "simulation": "whatif",
    "optimization": "whatif",
    "report": None,
}
_TYPE_ALIASES = {"explain": "attribution", "simulate": "simulation", "optimize": "optimization"}


def _as_steps(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item) for item in values if item not in (None, "")][-40:]


def _successful_output(item: Any) -> tuple[str | None, str, dict[str, Any] | None]:
    """Return (response_type, tool name, structured output) for one tool event."""
    if not isinstance(item, dict) or item.get("status") not in (None, "ok", "completed"):
        return None, "", None
    name = str(item.get("name") or item.get("tool") or "")
    output = item.get("output", item)
    if not isinstance(output, dict):
        return None, name, None
    kind = str(output.get("response_type") or "").strip().lower()
    kind = _TYPE_ALIASES.get(kind, kind)
    if kind not in RESPONSE_TYPES or kind in {"report", "need_input"}:
        return None, name, None
    return kind, name, output


def _table_from_rows(rows: Any) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return {"columns": [], "rows": []}
    keys = sorted({str(key) for row in clean_rows for key in row.keys()})
    return {
        "columns": [{"key": key, "title": key} for key in keys],
        "rows": clean_rows,
    }


def _text_block(value: Any, final_text: str) -> dict[str, Any]:
    if isinstance(value, dict):
        block = deepcopy(value)
    elif isinstance(value, str):
        block = {"markdown": value}
    else:
        block = {}
    block.setdefault("title", "分析解读")
    # The engine's final text is authoritative over capability prose.
    block["markdown"] = final_text or str(block.get("markdown") or "")
    return block


def build_envelope(
    final_text: str,
    tool_outputs: Iterable[dict[str, Any]] | None,
    process_steps: Iterable[str] | None,
    status: str,
) -> dict[str, Any]:
    """Build the stable T10 envelope from native successful tool outputs."""
    outputs = list(tool_outputs or [])
    selected_type = "report"
    selected_tool = "engine"
    selected: dict[str, Any] | None = None
    for item in outputs:
        kind, name, output = _successful_output(item)
        if kind and output is not None:
            selected_type, selected_tool, selected = kind, name or "engine", output

    source = deepcopy(selected.get("envelope")) if isinstance(selected, dict) and isinstance(selected.get("envelope"), dict) else {}
    if selected and not source:
        source = deepcopy(selected)

    envelope: dict[str, Any] = {
        "response_type": selected_type,
        "text": _text_block(source.get("text"), final_text),
        "meta": deepcopy(source.get("meta")) if isinstance(source.get("meta"), dict) else {},
        "follow_ups": deepcopy(source.get("follow_ups")) if isinstance(source.get("follow_ups"), list) else [],
        "update_workspace": bool(source.get("update_workspace", True)),
        "process_steps": _as_steps(list(process_steps or []) or source.get("process_steps")),
        "intent": _INTENT_BY_TYPE[selected_type],
    }
    if "chart" in source:
        envelope["chart"] = deepcopy(source["chart"])
    table = source.get("table")
    if isinstance(table, dict):
        envelope["table"] = deepcopy(table)
    elif selected is not None:
        rows = selected.get("rows")
        derived = _table_from_rows(rows)
        if derived is not None:
            envelope["table"] = derived

    meta = envelope["meta"]
    meta["status"] = status if status in {"completed", "interrupted", "failed"} else "failed"
    meta["tool"] = selected_tool
    return envelope


__all__ = ["RESPONSE_TYPES", "build_envelope"]
