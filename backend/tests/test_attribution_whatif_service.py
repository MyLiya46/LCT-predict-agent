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
            return _Result(self.datasets)
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
    assert result["elasticity_hits"] == 2
    assert result["items"][0]["plan_price"] == 10
