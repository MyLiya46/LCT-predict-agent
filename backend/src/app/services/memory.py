"""Small, deterministic conversation memory for the backup chat model."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation
from app.utils.errors import NotFoundError

ALLOWED_MEMORY_SLOTS = frozenset(
    {
        "category",
        "forecast_month",
        "horizon",
        "sku",
        "channel",
        "last_capability",
        "system_forecast_number",
    }
)


def normalize_slots(slots: dict[str, Any] | None) -> dict[str, Any]:
    """Drop unknown/oversized values and enforce the horizon contract."""
    if not isinstance(slots, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in slots.items():
        if key not in ALLOWED_MEMORY_SLOTS or value in (None, ""):
            continue
        if key == "horizon":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if not 1 <= value <= 12:
                continue
        elif not isinstance(value, str):
            value = str(value)
        if isinstance(value, str) and len(value) > 128:
            continue
        result[key] = value
    return result


sanitize_slots = normalize_slots


def _summary(slots: dict[str, Any], unfinished_input: str | None = None) -> str:
    labels = (
        ("category", "品类"),
        ("forecast_month", "月份"),
        ("system_forecast_number", "预测版本"),
        ("last_capability", "最近能力"),
        ("sku", "SKU"),
        ("channel", "渠道"),
        ("horizon", "预测跨度"),
    )
    parts = [f"{label}：{slots[key]}" for key, label in labels if key in slots]
    if unfinished_input:
        parts.append(f"未完成输入：{unfinished_input[:128]}")
    return "；".join(parts)[:2400]


async def update_memory(
    session: AsyncSession,
    conversation_id: str,
    *,
    owner_id: str | None = None,
    slots: dict[str, Any] | None = None,
    memory_slots: dict[str, Any] | None = None,
    unfinished_input: str | None = None,
    capability: str | None = None,
    commit: bool = True,
) -> Conversation:
    """Persist only confirmed structured slots and a bounded summary.

    Assistant prose is intentionally not summarized, so sales figures cannot
    be fabricated or accidentally promoted into long-lived memory.
    """
    conv = await session.get(Conversation, conversation_id)
    expected_owner = owner_id or session.info.get("owner_id")
    if conv is None or conv.status == "deleted" or (
        expected_owner is not None and str(conv.owner_id) != str(expected_owner)
    ):
        raise NotFoundError("会话不存在")
    merged = dict(conv.memory_slots or {})
    merged.update(normalize_slots(memory_slots or slots))
    if capability:
        merged.update(normalize_slots({"last_capability": capability}))
    conv.memory_slots = normalize_slots(merged)
    conv.memory_summary = _summary(conv.memory_slots, unfinished_input)
    if commit:
        await session.commit()
        await session.refresh(conv)
    return conv
