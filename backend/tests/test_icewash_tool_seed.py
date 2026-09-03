from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Tool
from seed.v2__icewash_tools import TOOLS, run_seed


@pytest.mark.asyncio
async def test_icewash_seed_is_idempotent(db_session_factory):
    await run_seed(db_session_factory())
    await run_seed(db_session_factory())
    async with db_session_factory() as session:
        rows = (await session.execute(select(Tool).where(Tool.name.in_(list(TOOLS))))).scalars().all()
        assert len(rows) == 7
        assert {row.execution.get("kind") for row in rows} == {"internal"}
        forecast = next(row for row in rows if row.name == "submit_forecast")
        assert forecast.execution["timeout_s"] == 300
