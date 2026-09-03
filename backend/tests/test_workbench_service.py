"""T04 PostgreSQL JSONB workbench query and pagination tests."""
from __future__ import annotations

import pytest

from app.models import WorkbenchDatasetRow
from app.services.workbench import list_datasets, query_table, get_filter_options_response


@pytest.mark.asyncio
async def test_workbench_metadata_jsonb_filter_and_page(db_session_factory):
    async with db_session_factory() as session:
        session.add_all([
            WorkbenchDatasetRow(
                dataset="cost_data", category="冰箱", sku="SKU-1",
                payload={"品类": "冰箱", "型号": "SKU-1", "成本价": 60},
            ),
            WorkbenchDatasetRow(
                dataset="fcst_detail", category="冰箱", sku="SKU-1", period="2026-09",
                payload={"品类": "冰箱", "型号": "SKU-1", "状态": "完成", "最终预测值": 3},
            ),
            WorkbenchDatasetRow(
                dataset="master_data", category="冰箱", sku="SKU-1",
                payload={"品类": "冰箱", "型号": "SKU-1", "product_status": "在售"},
            ),
            WorkbenchDatasetRow(
                dataset="rebate_data", category="冰箱", channel_l3="电商",
                payload={"品类": "冰箱", "3级渠道": "电商", "product_line_code": "PL003"},
            ),
        ])
        await session.commit()

        datasets = await list_datasets(session)
        assert len(datasets) == 8
        assert {item["key"] for item in datasets} == {
            "raw_data", "master_data", "price_data", "rebate_data", "dsi_data",
            "cost_data", "price_elasticity", "fcst_detail",
        }

        table = await query_table(session, "fcst_detail", category="冰箱", status="完成", page=1, page_size=1)
        assert table["total"] == 1
        assert table["rows"][0]["型号"] == "SKU-1"
        assert table["page"] == 1 and table["page_size"] == 1

        options = await get_filter_options_response(session, "cost_data")
        assert "冰箱" in options["filter_options"]["category"]

        master_options = await get_filter_options_response(session, "master_data")
        assert master_options["filter_options"]["status"] == ["在售"]

        rebate_options = await get_filter_options_response(session, "rebate_data")
        assert rebate_options["filter_options"]["product_line"] == ["PL003"]
