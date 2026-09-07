from __future__ import annotations

import pytest

from app.services.chat_envelope import build_envelope


class FixedToolCallMock:
    """Small deterministic tool trace used by the offline scenario checks."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def result(self, name: str, output: dict) -> dict:
        self.calls.append(name)
        return {"name": name, "status": "ok", "output": output}


def _forecast_output() -> dict:
    periods = ["2026-10", "2026-11", "2026-12"]
    return {
        "response_type": "forecast",
        "source_tool": "get_forecast_result",
        "system_forecast_number": "AG_洗衣机_2026-10",
        "category": "洗衣机",
        "horizon": 3,
        "monthly_totals": [
            {"horizon": f"N+{index}", "period": period, "forecast_qty": 100 + index * 10}
            for index, period in enumerate(periods, start=1)
        ],
        "top_skus": [
            {
                "rank": rank,
                "sku": f"WASH-{rank}",
                "series": [
                    {"horizon": f"N+{index}", "period": period, "forecast_qty": rank * 10 + index}
                    for index, period in enumerate(periods, start=1)
                ],
            }
            for rank in range(1, 6)
        ],
    }


def _attribution_output(sku: str) -> dict:
    return {
        "response_type": "attribution",
        "source_tool": "get_attribution",
        "system_forecast_number": "AG_洗衣机_2026-10",
        "category": "洗衣机",
        "sku": sku,
        "period": "2026-10",
        "qty_lag1": 90,
        "y_pred": 100,
        "factors": [{"name": "价格", "impact": 6}, {"name": "渠道", "impact": 4}],
        "trend": {
            "periods": ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"],
            "history": [80, 90, None, None, None],
            "forecast": [None, None, 100, 110, 120],
        },
        "waterfall": {
            "xAxis": ["基础销量", "价格", "渠道", "最终预测"],
            "placeholder": [90, 90, 96, 0],
            "values": [90, 6, 4, 100],
            "labels": ["90.0", "+6.0", "+4.0", "100.0"],
            "colors": ["#d9d9d9", "#52c41a", "#52c41a", "#003a8c"],
        },
    }


def _whatif_output(kind: str) -> dict:
    months = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
    rows = []
    for index, sku in enumerate(("FRIDGE-A", "FRIDGE-B", "FRIDGE-C"), start=1):
        details = []
        for month_index, month in enumerate(months, start=1):
            baseline_qty = float(index * 10 + month_index)
            sim_qty = round(baseline_qty * (1.1 if sku == "FRIDGE-A" else 1.0), 1)
            price = 100.0 if sku != "FRIDGE-C" else None
            sim_price = 92.0 if sku == "FRIDGE-A" else price
            details.append(
                {
                    "sku": sku,
                    "period": month,
                    "forecast_period": f"N+{month_index}",
                    "baseline_qty": baseline_qty,
                    "baseline_price": price,
                    "sim_qty": sim_qty,
                    "sim_price": sim_price,
                    "sim_amount": round(sim_qty * sim_price, 1) if sim_price is not None else None,
                    "sim_gross_profit": round(sim_qty * 30, 1) if sku == "FRIDGE-A" else None,
                }
            )
        strategy_id = "price_cut" if sku == "FRIDGE-A" else "maintain"
        rows.append(
            {
                "sku": sku,
                "series": "主销系列" if sku != "FRIDGE-C" else "新品系列",
                "status": "主销" if sku != "FRIDGE-C" else "新品",
                "strategy_id": strategy_id,
                "strategy_name": "降价促销" if strategy_id == "price_cut" else "维持现状",
                "param": "-8%" if strategy_id == "price_cut" else None,
                "baseline_qty": sum(item["baseline_qty"] for item in details),
                "sim_qty": sum(item["sim_qty"] for item in details),
                "baseline_price": 100.0 if sku != "FRIDGE-C" else None,
                "sim_price": 92.0 if sku == "FRIDGE-A" else (100.0 if sku == "FRIDGE-B" else None),
                "price_status": "complete" if sku != "FRIDGE-C" else "missing",
                "cost_status": "complete" if sku == "FRIDGE-A" else "missing",
                "gross_profit_status": "complete" if sku == "FRIDGE-A" else "missing",
                "details": details,
            }
        )
    return {
        "response_type": kind,
        "source_tool": "optimize" if kind == "optimization" else "simulate",
        "system_forecast_number": "AG_冰箱_2026-10",
        "category": "冰箱",
        "meta": {
            "target_qty": 423,
            "target_revenue": 100000,
            "assumptions": ["未提供目标销量，使用 PG What-if baseline summary.baseline_qty"],
            "baseline_summary": {
                "inventory_turnover_status": "unavailable",
                "inventory_turnover_reason": "缺少库存数据",
            },
        },
        "result": {"rows": rows},
        "envelope": {"chart": {"type": "legacy", "option": {"series": [{"data": [1]}]}}},
    }


def test_history_mock_uses_history_and_renders_three_sections():
    mock = FixedToolCallMock()
    output = {
        "response_type": "history",
        "source_tool": "get_history",
        "category": "冰箱",
        "rows": [{"period": "2026-04", "qty": 120}],
        "envelope": {
            "chart": {"type": "line", "option": {"xAxis": {"data": ["2026-04"]}}},
            "table": {"columns": [{"key": "period"}], "rows": [{"period": "2026-04", "qty": 120}]},
        },
    }
    result = build_envelope("历史销售分析", [mock.result("get_history", output)], [], "completed")

    assert mock.calls == ["get_history"]
    assert {"text", "chart", "table"} <= result.keys()
    assert result["response_type"] == "history"
    assert result["meta"]["tool"] == "get_history"
    assert "历史销售分析" == result["text"]["markdown"]


@pytest.mark.asyncio
async def test_forecast_without_base_month_returns_need_input():
    from app.tools.internal.submit_forecast.tool import handle as submit_forecast

    result = await submit_forecast({"category": "洗衣机", "horizon": 3})

    assert result["response_type"] == "need_input"
    assert result["missing"] == ["forecast_month"]


def test_forecast_mock_uses_submit_then_result_and_renders_line_and_table():
    mock = FixedToolCallMock()
    forecast = _forecast_output()
    result = build_envelope(
        "预测结果基于结构化预测明细",
        [mock.result("submit_forecast", forecast), mock.result("get_forecast_result", forecast)],
        [],
        "completed",
    )

    assert mock.calls == ["submit_forecast", "get_forecast_result"]
    assert {"text", "chart", "table"} <= result.keys()
    assert result["response_type"] == "forecast"
    assert [card["type"] for card in result["chart"]["cards"]] == ["line_band"]
    assert result["chart"]["cards"][0]["data"]["forecast"] == [110.0, 120.0, 130.0]
    assert len(result["table"]["rows"]) == 3
    assert result["meta"]["evidence"]["tools"] == ["submit_forecast", "get_forecast_result"]


def test_forecast_top5_mock_uses_forecast_version_for_attribution():
    mock = FixedToolCallMock()
    forecast = _forecast_output()
    events = [mock.result("submit_forecast", forecast), mock.result("get_forecast_result", forecast)]
    events.extend(mock.result("get_attribution", _attribution_output(f"WASH-{rank}")) for rank in range(1, 6))
    result = build_envelope("预测 TOP5 并引用白盒归因证据", events, [], "completed")

    assert mock.calls[:2] == ["submit_forecast", "get_forecast_result"]
    assert mock.calls[2:] == ["get_attribution"] * 5
    assert {"text", "chart", "table"} <= result.keys()
    cards = result["chart"]["cards"]
    assert [card["type"] for card in cards] == ["line_band", *(["waterfall"] * 5)]
    assert len(cards[0]["data"]["top_skus"]) == 5
    assert [card["data"]["sku"] for card in cards[1:]] == [f"WASH-{rank}" for rank in range(1, 6)]
    assert [card["title"] for card in cards[1:]] == [f"白盒归因 · WASH-{rank}" for rank in range(1, 6)]
    assert result["meta"]["evidence"]["attribution_count"] == 5
    assert result["meta"]["evidence"]["matched_attribution_count"] == 5


@pytest.mark.parametrize(
    ("kind", "sequence"),
    [
        ("optimization", ["optimize"]),
        ("simulation", ["get_whatif_strategies", "simulate"]),
    ],
)
def test_whatif_mock_renders_strategy_matrix_and_cumulative_dashboard(kind: str, sequence: list[str]):
    mock = FixedToolCallMock()
    events = []
    if kind == "simulation":
        events.append(mock.result("get_whatif_strategies", {"response_type": "whatif_strategies", "strategies": []}))
    events.append(mock.result("simulate" if kind == "simulation" else "optimize", _whatif_output(kind)))
    result = build_envelope("What-if 汇总分析", events, [], "completed", limit=1)

    assert mock.calls == sequence
    assert {"text", "chart", "table"} <= result.keys()
    assert result["response_type"] == kind
    assert [card["type"] for card in result["chart"]["cards"]] == ["strategy_matrix", "attainment_trend"]
    assert result["table"]["total"] == 3
    assert len(result["table"]["rows"]) == 3
    assert all(row["strategy_name"] for row in result["table"]["rows"])
    trend = result["chart"]["cards"][1]["data"]
    assert trend["cumulative"] is True
    assert len(trend["months"]) == 6
    assert trend["target"]["qty"][-1] == 423.0
    assert all(value is None for value in trend["simulated"]["amount"])
    missing = next(row for row in result["table"]["rows"] if row["sku"] == "FRIDGE-C")
    assert missing["sim_amount"] is None
    assert missing["sim_gross_profit"] is None
    assert missing["inventory_turnover_days"] is None
    assert missing["inventory_status"] == "unavailable"
    assert "库存" in missing["inventory_reason"]
    assert result["text"]["metrics"]["qty_attainment"] is not None
    assert result["text"]["metrics"]["amount_attainment"] is None
