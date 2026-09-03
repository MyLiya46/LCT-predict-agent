from __future__ import annotations

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
                    series="V", status="主销", channel_l3="京东", sku="R-1", final_value=12,
                ),
                FcstAttribution(
                    system_forecast_number=version, forecast_month="2026-08", horizon="N+1",
                    category="冰箱", series="V", status="主销", channel_l3="京东", sku="R-1",
                    factor_type="price", y_pred=12, delta_y=2,
                ),
                FcstHistory(period="2026-07", category="冰箱", channel_l3="京东", sku="R-1", qty=10),
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
        assert attr and attr.qty_lag1 == 10 and attr.impact == 2
        assert history and history.retail_qty == 10 and history.retail_amt is None
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

