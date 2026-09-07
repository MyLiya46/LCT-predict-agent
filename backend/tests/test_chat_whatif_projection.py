from __future__ import annotations

from app.services.chat_envelope import build_envelope


def _whatif_output(kind: str = "optimization") -> dict:
    months = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
    rows = []
    for index, sku in enumerate(("SKU-A", "SKU-B", "SKU-C"), start=1):
        details = []
        for month_index, month in enumerate(months, start=1):
            qty = float(index * 10 + month_index)
            details.append(
                {
                    "sku": sku,
                    "period": month,
                    "forecast_period": f"N+{month_index}",
                    "forecast_qty": qty,
                    "baseline_qty": qty,
                    "baseline_price": 100 if sku != "SKU-C" else None,
                    "cost_price": 60 if sku == "SKU-A" else None,
                    "sim_qty": qty * 1.1,
                    "sim_price": 110 if sku != "SKU-C" else None,
                    "sim_amount": qty * 1.1 * 110 if sku != "SKU-C" else None,
                    "sim_gross_profit": qty * 1.1 * 50 if sku == "SKU-A" else None,
                }
            )
        rows.append(
            {
                "sku": sku,
                "series": "主系列",
                "status": "主销",
                "strategy_id": "price_cut" if kind == "optimization" else "traffic_boost",
                "strategy_name": "降价促销" if kind == "optimization" else "加大投流",
                "param": "-8%" if kind == "optimization" else "+12%",
                "baseline_qty": sum(item["baseline_qty"] for item in details),
                "sim_qty": sum(item["sim_qty"] for item in details),
                "baseline_price": 100 if sku != "SKU-C" else None,
                "sim_price": 110 if sku != "SKU-C" else None,
                "sim_amount": sum(item["sim_amount"] for item in details if item["sim_amount"] is not None)
                if sku != "SKU-C"
                else None,
                "sim_gross_profit": sum(item["sim_gross_profit"] for item in details if item["sim_gross_profit"] is not None)
                if sku == "SKU-A"
                else None,
                "price_status": "complete" if sku != "SKU-C" else "missing",
                "cost_status": "complete" if sku == "SKU-A" else "missing",
                "gross_profit_status": "complete" if sku == "SKU-A" else "missing",
                "details": details,
            }
        )
    return {
        "response_type": kind,
        "source_tool": "optimize" if kind == "optimization" else "simulate",
        "system_forecast_number": "F-WHATIF-1",
        "category": "冰箱",
        "meta": {
            "target_qty": 396,
            "target_revenue": 100000,
            "assumptions": ["未提供目标销量，使用 PG What-if baseline summary.baseline_qty"],
            "baseline_summary": {
                "inventory_turnover_status": "unavailable",
                "inventory_turnover_reason": "缺少库存数据",
            },
        },
        "envelope": {
            "status": "completed",
            "result": {"rows": rows},
            "text": {"title": "", "markdown": ""},
            "chart": {"type": "legacy", "option": {"series": [{"data": [1]}]}},
        },
    }


def test_whatif_projection_keeps_full_matrix_and_cumulative_targets():
    result = build_envelope(
        "",
        [{"name": "optimize", "status": "ok", "output": _whatif_output()}],
        [],
        "completed",
        limit=1,
    )

    assert result["response_type"] == "optimization"
    assert [card["type"] for card in result["chart"]["cards"]] == [
        "strategy_matrix",
        "attainment_trend",
    ]
    assert result["table"]["total"] == 3
    assert len(result["table"]["rows"]) == 3
    trend = result["chart"]["cards"][1]["data"]
    assert trend["months"] == ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
    assert trend["cumulative"] is True
    assert trend["target"]["qty"][-1] == 396.0
    assert trend["target"]["qty"][0] != trend["target"]["qty"][-1]
    assert result["text"]["metrics"]["baseline_to_target_qty_gap"] == -27.0
    assert result["text"]["metrics"]["simulated_to_target_qty_gap"] == -69.3
    assert result["chart"]["option"]["series"][0]["data"] == [1]
    assert result["text"]["markdown"]
    assert result["text"]["metrics"]["qty_attainment"] is not None


def test_whatif_projection_exposes_missing_amount_cost_inventory_as_null_state():
    result = build_envelope(
        "计划报告",
        [{"name": "simulate", "status": "ok", "output": _whatif_output("simulation")}],
        [],
        "completed",
    )
    missing = next(row for row in result["table"]["rows"] if row["sku"] == "SKU-C")
    assert missing["sim_amount"] is None
    assert missing["sim_gross_profit"] is None
    assert missing["inventory_turnover_days"] is None
    assert missing["inventory_status"] == "unavailable"
    assert "库存" in missing["inventory_reason"]
    trend = result["chart"]["cards"][1]["data"]
    assert all(value is None for value in trend["simulated"]["amount"])
    assert result["text"]["markdown"] == "计划报告"


def test_whatif_projection_uses_full_baseline_summary_for_amount_trend():
    output = _whatif_output()
    output["meta"]["baseline_summary"].update(
        {
            "months": ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"],
            "amount_series": [1000, 2000, 3000, 4000, 5000, 6000],
        }
    )

    result = build_envelope(
        "",
        [{"name": "optimize", "status": "ok", "output": output}],
        [],
        "completed",
    )

    trend = result["chart"]["cards"][1]["data"]
    assert trend["baseline"]["amount"] == [1000.0, 3000.0, 6000.0, 10000.0, 15000.0, 21000.0]
    assert all(value is None for value in trend["simulated"]["amount"])
