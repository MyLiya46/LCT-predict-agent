from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import AttributionAnalysisRow, ForecastHistoryRow, WorkbenchDatasetRow
from app.services.attribution_workbench import filter_options, list_skus, sku_detail, trend_series
from app.services.whatif_workbench import load_baseline


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)


class _Session:
    def __init__(self, attribution, history, datasets):
        self.attribution = attribution
        self.history = history
        self.datasets = datasets

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AttributionAnalysisRow:
            return _Result(self.attribution)
        if entity is ForecastHistoryRow:
            return _Result(self.history)
        if entity is WorkbenchDatasetRow:
            params = statement.compile().params
            dataset = params.get("dataset_1")
            version = params.get("version_1")
            rows = [row for row in self.datasets if not dataset or row.dataset == dataset]
            if version:
                rows = [row for row in rows if row.version == version]
            return _Result(rows)
        return _Result([])


def _attr(**changes):
    values = dict(
        id="id", category="冰箱", version="v1", period="2026-09", horizon="N+1", sku="A",
        status="主销", series="X", channel_l1="线上", channel_l3="旗舰店", attr_type="价格",
        y_pred=110, qty_lag1=100, impact=10, payload={},
    )
    values.update(changes)
    return SimpleNamespace(**values)


def _history(**changes):
    values = dict(
        id="history", category="冰箱", version="v1", period="2026-08", sku="A", status="主销",
        series="X", channel_l1="线上", channel_l3="旗舰店", retail_qty=90, retail_amt=900, payload={},
    )
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.fixture
def session():
    attrs = [
        _attr(id="1", period="2026-09", horizon="N+1", attr_type="价格", impact=10),
        _attr(id="2", period="2026-09", horizon="N+1", attr_type="MA_vs_qty_lag1", impact=100, payload={"影响因子": "MA_vs_qty_lag1"}),
        _attr(id="3", period="2026-10", horizon="N+2", attr_type="渠道", impact=20),
        _attr(id="4", sku="B", period="2026-09", y_pred=50, qty_lag1=40),
    ]
    datasets = [
        SimpleNamespace(dataset="fcst_detail", category="冰箱", version="v1", period="2026-09", sku="A", channel_l3="旗舰店", payload={"计划价格": 10}, created_at=None, id="d1"),
        SimpleNamespace(dataset="price_elasticity", category="冰箱", version=None, period=None, sku="A", channel_l3=None, payload={"价格弹性系数": 1.2, "弹性类别": "价格敏感"}, created_at=None, id="e1"),
    ]
    return _Session(attrs, [_history()], datasets)


@pytest.mark.asyncio
async def test_attribution_contracts_and_top_tags(session):
    options = await filter_options(session)
    assert all(options[key] for key in ("category", "version", "status"))
    skus = await list_skus(session, category="冰箱", version="v1", tag="Top5")
    assert len(skus["items"]) <= 5
    detail = await sku_detail(session, category="冰箱", version="v1", sku="A")
    assert detail["ok"] is True
    assert detail["waterfall"] and detail["type_impacts"] == [{"type": "价格", "impact": 10.0}, {"type": "渠道", "impact": 20.0}]
    trend = await trend_series(session, category="冰箱", version="v1", sku="A")
    assert trend["split_period"] == "2026-09"
    assert trend["history"][0] is not None and trend["forecast"][1] is not None


@pytest.mark.asyncio
async def test_baseline_is_pg_db_source_and_counts_elasticity(session):
    result = await load_baseline(session, category="冰箱", version="v1")
    assert result["source"] == "db"
    assert result["items"]
    assert result["elasticity_hits"] == 1
    assert result["total"] == 2
    assert result["items"][0]["sku"] == "A"
    assert result["items"][0]["plan_price"] == 10
    assert result["items"][0]["price_source"] == "mixed"
    assert result["items"][0]["price_base_month"] is None
    assert len(result["items"][0]["details"]) == 2
    assert result["items"][0]["details"][0]["forecast_qty"] == 110
    assert result["items"][0]["details"][0]["baseline_price"] == 10
    assert result["items"][0]["details"][0]["price_source"] == "forecast_plan"
    assert result["items"][0]["details"][1]["baseline_price"] == 10
    assert result["items"][0]["details"][1]["price_source"] == "historical_last_valid_month"
    assert result["items"][0]["details"][1]["price_base_month"] == "2026-08"
    assert result["summary"]["months"] == ["2026-09", "2026-10"]
    assert result["summary"]["qty_series"] == [160.0, 110.0]
    assert result["summary"]["amount_series"] == [1100.0, 1100.0]
    assert result["summary"]["baseline_qty"] == 270.0
    assert result["summary"]["baseline_amount"] == 2200.0
    assert result["summary"]["inventory_turnover_days"] is None
    assert result["summary"]["inventory_turnover_label"] == "45天（占位）"
    assert result["summary"]["inventory_turnover_status"] == "unavailable"
    assert "库存" in result["summary"]["inventory_turnover_reason"]

    limited = await load_baseline(session, category="冰箱", version="v1", limit=1)
    assert limited["total"] == 2
    assert limited["summary"]["baseline_qty"] == 270.0
    assert limited["summary"]["baseline_amount"] == 2200.0
    assert len(limited["items"]) == 1


@pytest.mark.asyncio
async def test_baseline_resolves_plan_before_history_and_keeps_missing_null():
    months = ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
    attrs = [
        _attr(id=f"a-{index}", period=month, horizon=f"N+{index + 1}", y_pred=100)
        for index, month in enumerate(months)
    ]
    attrs.extend(
        [
            _attr(id="cross", sku="C", period="2026-09", horizon="N+1", y_pred=20, channel_l3="京东"),
            _attr(id="batch", sku="D", period="2026-09", horizon="N+1", y_pred=30, channel_l3="京东"),
            _attr(id="missing", sku="E", period="2026-09", horizon="N+1", y_pred=40, channel_l3="京东"),
        ]
    )
    history = [
        _history(id="a-old", period="2026-07", retail_qty=100, retail_amt=1100),
        _history(id="a-latest-1", period="2026-08", retail_qty=90, retail_amt=900),
        _history(id="a-latest-2", period="2026-08", retail_qty=10, retail_amt=100),
        _history(id="a-other-channel", period="2026-08", retail_qty=100, retail_amt=2000, channel_l3="天猫"),
        _history(id="c-other-channel", sku="C", period="2026-08", retail_qty=50, retail_amt=1000, channel_l3="天猫"),
        _history(id="e-invalid-qty", sku="E", period="2026-08", retail_qty=0, retail_amt=500),
        _history(id="e-invalid-amt", sku="E", period="2026-07", retail_qty=10, retail_amt=None),
    ]
    datasets = [
        SimpleNamespace(
            dataset="fcst_detail",
            category="冰箱",
            version="v1",
            period="2026-09",
            sku="A",
            channel_l3="旗舰店",
            payload={"plan_price": 12},
            created_at=None,
            id="detail-null",
        ),
        SimpleNamespace(
            dataset="price_data",
            category="冰箱",
            version="JG_v1",
            period="2026-09",
            sku="D",
            channel_l3="京东",
            payload={"计划价格": 33},
            created_at=None,
            id="price-batch",
        ),
    ]
    isolated = _Session(attrs, history, datasets)

    result = await load_baseline(isolated, category="冰箱", version="v1")
    items = {item["sku"]: item for item in result["items"]}

    history_item = items["A"]
    assert history_item["price_source"] == "mixed"
    assert history_item["price_base_month"] is None
    assert history_item["plan_price"] == 12
    assert len(history_item["details"]) == 6
    assert history_item["details"][0]["baseline_price"] == 12
    assert history_item["details"][0]["price_source"] == "forecast_plan"
    assert history_item["details"][0]["plan_price"] == 12
    assert all(detail["baseline_price"] == 10 for detail in history_item["details"][1:])
    assert all(detail["price_source"] == "historical_last_valid_month" for detail in history_item["details"][1:])
    assert history_item["details"][0]["baseline_amount"] == 1200
    assert all(detail["baseline_amount"] == 1000 for detail in history_item["details"][1:])

    assert items["C"]["baseline_price"] == 20
    assert items["C"]["plan_price"] is None
    assert items["C"]["price_source"] == "historical_last_valid_month"
    assert items["D"]["baseline_price"] == 33
    assert items["D"]["plan_price"] == 33
    assert items["D"]["price_source"] == "price_data"
    assert items["D"]["price_base_month"] == "2026-09"

    assert items["E"]["plan_price"] is None
    assert items["E"]["price_source"] is None
    assert items["E"]["price_status"] == "missing"
    assert items["E"]["details"][0]["baseline_price"] is None
    assert items["E"]["details"][0]["baseline_amount"] is None
    assert result["summary"]["baseline_amount"] == 6200 + 400 + 990
