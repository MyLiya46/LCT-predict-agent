from __future__ import annotations

from sqlalchemy import select

from app.models import FcstAttribution, FcstForecastResult, FcstHistory, WorkbenchDatasetRow
from app.services.forecast_relay_ingest import sync_forecast_relay
from app.services.whatif_workbench import load_baseline


async def test_prediction_detail_contract_keeps_missing_price_null(db_session_factory):
    version = "AG_冰箱_2026-09"
    async with db_session_factory() as session:
        session.add(
            FcstForecastResult(
                system_forecast_number=version,
                horizon="N+2",
                forecast_month="2026-10-01",
                category="冰箱",
                channel_l3="天猫",
                sku="R-2",
                final_value=21,
                plan_price=None,
            )
        )
        await session.commit()
        await sync_forecast_relay(session, version)
        detail = (await session.execute(select(WorkbenchDatasetRow))).scalars().first()

    assert detail is not None
    assert detail.payload["version"] == version
    assert detail.payload["month"] == "2026-10"
    assert detail.payload["forecast_period"] == "N+2"
    assert detail.payload["forecast_qty"] == 21
    assert detail.payload["plan_price"] is None
    assert "forecast_price" not in detail.payload


async def test_null_prediction_prices_use_relayed_historical_baseline(db_session_factory):
    version = "AG_冰箱_2026-09-history"
    months = ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
    async with db_session_factory() as session:
        session.add_all(
            [
                FcstForecastResult(
                    system_forecast_number=version,
                    horizon=f"N+{index + 1}",
                    forecast_month=month,
                    category="冰箱",
                    channel_l3="京东",
                    sku="R-3",
                    final_value=10,
                    plan_price=None,
                )
                for index, month in enumerate(months)
            ]
            + [
                FcstAttribution(
                    system_forecast_number=version,
                    horizon=f"N+{index + 1}",
                    forecast_month=month,
                    category="冰箱",
                    channel_l3="京东",
                    sku="R-3",
                    y_pred=10,
                    delta_y=1,
                )
                for index, month in enumerate(months)
            ]
            + [
                FcstHistory(
                    period="2026-08",
                    category="冰箱",
                    channel_l3="京东",
                    sku="R-3",
                    qty=90,
                    retail_amt=900,
                )
            ]
        )
        await session.commit()
        await sync_forecast_relay(session, version)
        baseline = await load_baseline(session, category="冰箱", version=version)

    item = baseline["items"][0]
    assert item["price_source"] == "historical_last_valid_month"
    assert item["price_base_month"] == "2026-08"
    assert len(item["details"]) == 6
    assert all(detail["baseline_price"] == 10 for detail in item["details"])
    assert all(detail["plan_price"] is None for detail in item["details"])
    assert all(detail["baseline_amount"] == 100 for detail in item["details"])
    assert baseline["summary"]["baseline_amount"] == 600
