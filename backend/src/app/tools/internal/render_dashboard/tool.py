"""render_dashboard 内置工具（T43）：进程内校验并规整看板 spec。

输入 = AI 生成的图表 spec（与 schema.json 同构）；输出 = 规整后的 spec（补齐默认值）。
非法输入 → 抛 ValidationError，由引擎归一为 tool_error(VALIDATION)。
"""
from __future__ import annotations

from typing import Any

import jsonschema

from app.utils.errors import ValidationError

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": ["single", "grid"]},
        "cards": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "card_type": {"type": "string", "enum": ["line", "bar", "table"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "labels": {"type": "array", "items": {"type": "string"}},
                            "series": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "values": {"type": "array", "items": {"type": "number"}},
                                    },
                                    "required": ["name", "values"],
                                },
                            },
                        },
                        "required": ["labels", "series"],
                    },
                },
                "required": ["card_type", "title", "data"],
            },
        },
    },
    "required": ["cards"],
}


def _normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "card_type": card.get("card_type", "table"),
        "title": card.get("title", ""),
        "data": card.get("data", {"labels": [], "series": []}),
    }
    if card.get("description"):
        out["description"] = card["description"]
    return out


async def handle(input_data: dict[str, Any]) -> dict[str, Any]:
    """校验并规整 spec，输出与输入同构的统一 spec。"""
    try:
        jsonschema.validate(instance=input_data, schema=_INPUT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"看板 spec 非法: {exc.message}") from exc

    cards = [_normalize_card(c) for c in input_data.get("cards", [])]
    layout = input_data.get("layout") or ("single" if len(cards) == 1 else "grid")
    return {"layout": layout, "cards": cards}
