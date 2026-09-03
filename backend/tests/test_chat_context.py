from __future__ import annotations

import pytest

from app.services.memory import normalize_slots


def test_memory_slots_whitelist_and_limits():
    slots = normalize_slots({"category": "冰箱", "unknown": "drop", "horizon": 13, "sku": "x" * 129})
    assert slots == {"category": "冰箱"}
    assert normalize_slots({"horizon": "12", "last_capability": "history"})["horizon"] == 12


def test_memory_summary_limit_is_constant():
    from app.services.memory import _summary

    assert len(_summary({"category": "冰箱"}, "x" * 5000)) <= 2400


@pytest.mark.asyncio
async def test_context_owner_check_is_explicit():
    from unittest.mock import AsyncMock

    from app.services.chat_context import build_context
    from app.utils.errors import NotFoundError

    session = AsyncMock()
    session.info = {}
    conv = type("Conversation", (), {"status": "active", "owner_id": "owner-a"})()
    session.get.return_value = conv
    with pytest.raises(NotFoundError):
        await build_context(session, "c1", "hello", owner_id="owner-b")
