"""T04 model reference client and idempotent PG replacement tests."""
from __future__ import annotations

import pytest
import respx
from httpx import Response
from sqlalchemy import func, select

from app.models import WorkbenchDatasetRow
from app.services.model_reference_client import sync_reference_dataset, upload_cost_reference


@pytest.mark.asyncio
async def test_reference_sync_replaces_without_duplicates(db_session_factory):
    payload = {
        "dataset": "cost_data",
        "rows": [
            {"品类": "冰箱", "型号": "T04-SKU", "建议零售价": 100, "成本价": 60},
        ],
    }
    async with db_session_factory() as session:
        assert await sync_reference_dataset(session, "cost_data", payload) == 1
        assert await sync_reference_dataset(session, "cost_data", payload) == 1
        count = await session.scalar(
            select(func.count()).select_from(WorkbenchDatasetRow).where(
                WorkbenchDatasetRow.dataset == "cost_data"
            )
        )
        row = (await session.execute(select(WorkbenchDatasetRow))).scalars().first()
        assert count == 1
        assert row is not None and row.category == "冰箱" and row.sku == "T04-SKU"


@pytest.mark.asyncio
@respx.mock
async def test_cost_upload_fetches_normalized_rows_after_model_ack():
    upload = respx.post("http://127.0.0.1:8001/reference/workbench/cost_data").mock(
        return_value=Response(
            200,
            json={
                "dataset": "cost_data",
                "row_count": 1,
                "source": "services/icewash-model/data/reference/cost_data.xlsx",
            },
        )
    )
    fetch = respx.get("http://127.0.0.1:8001/reference/workbench/cost_data").mock(
        return_value=Response(
            200,
            json={
                "dataset": "cost_data",
                "rows": [{"品类": "冰箱", "型号": "T04-UPLOAD", "成本价": 60}],
                "row_count": 1,
            },
        )
    )

    payload = await upload_cost_reference(b"cost-data", "cost_data.csv")

    assert payload["rows"][0]["型号"] == "T04-UPLOAD"
    assert upload.called and fetch.called
