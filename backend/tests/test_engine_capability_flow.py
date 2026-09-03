from __future__ import annotations

import pytest

from app.tools.internal.get_history.tool import handle


@pytest.mark.asyncio
async def test_capability_tool_result_is_structured():
    async def client(data):
        return {"rows": [{"category": data["category"]}]}

    result = await handle({"category": "冰箱"}, {"get_history": client})
    assert result["response_type"] == "history"
    assert result["rows"][0]["category"] == "冰箱"
