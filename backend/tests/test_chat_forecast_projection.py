from __future__ import annotations

from copy import deepcopy

from app.services.chat_envelope import build_envelope


def _forecast() -> dict:
    periods = ["2026-10", "2026-11", "2026-12"]
    return {
        "response_type": "forecast",
        "source_tool": "submit_forecast",
        "system_forecast_number": "F1",
        "category": "洗衣机",
        "horizon": 3,
        "monthly_totals": [
            {"horizon": "N+1", "period": periods[0], "forecast_qty": 100},
            {"horizon": "N+2", "period": periods[1], "forecast_qty": 110},
            {"horizon": "N+3", "period": periods[2], "forecast_qty": 120},
        ],
        "top_skus": [
            {
                "rank": rank,
                "sku": f"SKU-{rank}",
                "series": [
                    {"period": period, "horizon": f"N+{index}", "forecast_qty": rank * 10 + index}
                    for index, period in enumerate(periods, 1)
                ],
            }
            for rank in range(1, 6)
        ],
        "envelope": {
            "text": {"title": "销量预测", "markdown": ""},
            "chart": {"type": "line", "option": {"xAxis": {"data": periods}}},
            "table": {"columns": [{"key": "period"}], "rows": []},
        },
    }


def _attribution(*, version: str = "F1", sku: str = "SKU-1") -> dict:
    return {
        "response_type": "attribution",
        "source_tool": "get_attribution",
        "system_forecast_number": version,
        "category": "洗衣机",
        "sku": sku,
        "period": "2026-10",
        "qty_lag1": 90,
        "y_pred": 100,
        "trend": {
            "periods": ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"],
            "history": [80, None, 90, None, None],
            "forecast": [None, None, 100, 110, 120],
            "split_period": "2026-10",
        },
        "waterfall": {
            "xAxis": ["基础销量", "价格", "渠道", "季节", "最终预测"],
            "placeholder": [90, 90, 95, 100, 0],
            "values": [90, 5, 5, 0, 100],
            "labels": ["90.0", "+5.0", "+5.0", "0.0", "100.0"],
            "colors": ["#d9d9d9", "#52c41a", "#52c41a", "#52c41a", "#003a8c"],
        },
        "envelope": {"text": {"title": "预测归因分析", "markdown": ""}},
    }


def test_forecast_projection_hides_top5_without_attribution():
    forecast = _forecast()
    result = build_envelope(
        "",
        [{"name": "submit_forecast", "status": "ok", "output": forecast}],
        [],
        "completed",
        limit=1,
    )

    assert result["response_type"] == "forecast"
    assert result["text"]["markdown"]
    assert [card["type"] for card in result["chart"]["cards"]] == ["line_band"]
    line = result["chart"]["cards"][0]["data"]
    assert line["periods"] == ["2026-10", "2026-11", "2026-12"]
    assert line["history"] == [None, None, None]
    assert line["forecast"] == [100.0, 110.0, 120.0]
    assert line["top_skus"] == []
    assert len(result["table"]["rows"]) == 3
    assert result["chart"]["option"]["xAxis"]["data"] == line["periods"]


def test_forecast_and_attribution_are_aggregated_and_mismatch_is_not_charted():
    forecast = _forecast()
    outputs = [
        {"name": "submit_forecast", "status": "ok", "output": forecast},
        {"name": "get_attribution", "status": "ok", "output": _attribution()},
        {"name": "get_attribution", "status": "ok", "output": _attribution(version="OLD", sku="SKU-2")},
    ]
    result = build_envelope("", outputs, [], "completed")
    cards = result["chart"]["cards"]
    assert result["response_type"] == "forecast"
    assert [card["type"] for card in cards] == ["line_band", "waterfall"]
    line = cards[0]["data"]
    assert line["periods"] == ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
    assert line["history"] == [80.0, None, 90.0, None, None]
    assert line["forecast"] == [None, None, 100.0, 110.0, 120.0]
    assert len(line["top_skus"]) == 5
    assert all(item["periods"] == ["2026-10", "2026-11", "2026-12"] for item in line["top_skus"])
    assert result["meta"]["evidence"]["tools"] == ["submit_forecast", "get_attribution"]
    assert result["meta"]["evidence"]["forecast_count"] == 1
    assert result["meta"]["evidence"]["attribution_count"] == 2
    assert len(result["meta"]["evidence"]["mismatches"]) == 1
    assert cards[1]["data"]["sku"] == "SKU-1"


def test_duplicate_attribution_is_deduped_and_old_report_chart_is_untouched():
    attr = _attribution()
    result = build_envelope(
        "文本",
        [
            {"name": "submit_forecast", "status": "ok", "output": _forecast()},
            {"name": "get_attribution", "status": "ok", "output": attr},
            {"name": "get_attribution", "status": "ok", "output": deepcopy(attr)},
        ],
        [],
        "completed",
    )
    assert len(result["chart"]["cards"]) == 2
    assert result["text"]["markdown"] == "文本"

    legacy = {
        "response_type": "history",
        "envelope": {"chart": {"type": "line", "option": {"series": [{"data": [1]}]}}},
    }
    old = build_envelope("历史", [{"name": "get_history", "status": "ok", "output": legacy}], [], "completed")
    assert old["chart"] == legacy["envelope"]["chart"]
