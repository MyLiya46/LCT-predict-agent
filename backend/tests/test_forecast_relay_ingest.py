from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import (
    AttributionAnalysisRow,
    FcstAttribution,
    FcstForecastResult,
    FcstHistory,
    ForecastHistoryRow,
    WorkbenchDatasetRow,
)
from app.services.forecast_relay_ingest import sync_forecast_relay


async def test_relay_maps_and_is_idempotent(db_session_factory):
    version = "AG_冰箱_2026-08"
    async with db_session_factory() as session:
        session.add_all(
            [
                FcstForecastResult(
                    system_forecast_number=version, forecast_month="2026-08", category="冰箱",
                    horizon="N+1", series="V", status="主销", channel_l3="京东", sku="R-1", final_value=12,
                    plan_price=1999,
                ),
                FcstAttribution(
                    system_forecast_number=version, forecast_month="2026-08", horizon="N+1",
                    category="冰箱", series="V", status="主销", channel_l3="京东", sku="R-1",
                    factor_type="price", y_pred=12, delta_y=2,
                ),
                FcstHistory(
                    period="2026-07",
                    category="冰箱",
                    channel_l3="京东",
                    sku="R-1",
                    qty=10,
                    retail_amt=900,
                ),
                FcstHistory(period="2026-07", category="洗衣机", channel_l3="京东", sku="W-1", qty=20),
            ]
        )
        await session.commit()
        result = await sync_forecast_relay(session, version, category="冰箱", sku="R-1")
        assert result == {"forecast_rows": 1, "attribution_rows": 1, "history_rows": 1}
        detail = (await session.execute(select(WorkbenchDatasetRow))).scalars().first()
        attr = (await session.execute(select(AttributionAnalysisRow))).scalars().first()
        history = (await session.execute(select(ForecastHistoryRow))).scalars().first()
        assert detail and detail.payload["版本号"] == version and detail.payload["最终预测值"] == 12
        assert detail.payload["version"] == version
        assert detail.payload["month"] == "2026-08"
        assert detail.payload["forecast_period"] == "N+1"
        assert detail.payload["sku"] == "R-1"
        assert detail.payload["channel"] == "京东"
        assert detail.payload["forecast_qty"] == 12
        assert detail.payload["plan_price"] == 1999
        assert "forecast_price" not in detail.payload
        assert attr and attr.qty_lag1 == 10 and attr.impact == 2
        assert history and history.retail_qty == 10 and history.retail_amt == 900
        before = [
            await session.scalar(select(func.count()).select_from(WorkbenchDatasetRow)),
            await session.scalar(select(func.count()).select_from(AttributionAnalysisRow)),
            await session.scalar(select(func.count()).select_from(ForecastHistoryRow)),
        ]
        await sync_forecast_relay(session, version, category="冰箱", sku="R-1")
        after = [
            await session.scalar(select(func.count()).select_from(WorkbenchDatasetRow)),
            await session.scalar(select(func.count()).select_from(AttributionAnalysisRow)),
            await session.scalar(select(func.count()).select_from(ForecastHistoryRow)),
        ]
        assert before == after == [1, 1, 1]


def test_history_to_pg_frame_preserves_numeric_retail_amount_and_nulls(tmp_path):
    pd = pytest.importorskip("pandas")
    import sys
    from pathlib import Path

    service_dir = Path(__file__).resolve().parents[2] / "services" / "icewash-model" / "cbg_fcst_month"
    sys.path.insert(0, str(service_dir))
    from pg_sync import history_to_pg_frame

    csv_path = tmp_path / "history.csv"
    pd.DataFrame(
        {
            "period_id": ["2026-07", "2026-08"],
            "category_name": ["冰箱", "冰箱"],
            "channel_name_l3": ["京东", "京东"],
            "product_mode_name": ["R-1", "R-2"],
            "retail_qty": [10, 20],
            "retail_amt": ["900", ""],
        }
    ).to_csv(csv_path, index=False)

    frame = history_to_pg_frame(str(csv_path))
    assert list(frame.columns) == ["period", "category", "channel_l3", "sku", "qty", "retail_amt"]
    assert frame.loc[0, "retail_amt"] == 900
    assert pd.isna(frame.loc[1, "retail_amt"])
