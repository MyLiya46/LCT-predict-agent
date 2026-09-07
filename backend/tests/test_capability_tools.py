from __future__ import annotations

import pytest

from app.tools.internal.get_attribution.tool import handle as attribution
from app.tools.internal.get_forecast_result.tool import handle as forecast_result
from app.tools.internal.get_history.tool import handle as history
from app.tools.internal.get_task_status.tool import handle as task_status
from app.tools.internal.get_whatif_strategies.tool import handle as strategies
from app.tools.internal.optimize.tool import handle as optimize
from app.tools.internal.simulate.tool import handle as simulate
from app.tools.internal.submit_forecast.tool import _forecast_payload
from app.tools.internal.submit_forecast.tool import handle as submit_forecast
from seed.v2__icewash_tools import TOOLS


@pytest.mark.asyncio
async def test_capabilities_need_input_and_response_types():
    assert (await history({}))['response_type'] == 'need_input'
    assert (await submit_forecast({}))['response_type'] == 'need_input'
    assert (await attribution({}))['response_type'] == 'need_input'

    row_calls = []

    async def rows(*args, **kwargs):
        row_calls.append((args, kwargs))
        return [{"sku": "S1", "baseline_qty": 2}]

    calls = []

    async def simulate_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": []}}

    result = await simulate(
        {"system_forecast_number": "F1", "category": "冰箱", "strategy_id": "discount", "param": {"x": 1}},
        {"build_whatif_rows": rows, "simulate": simulate_client},
    )
    assert result['response_type'] == 'simulation'
    assert set(calls[0]) == {"strategy_id", "param", "rows"}
    assert row_calls[0][0][2] == "冰箱"

    calls.clear()

    async def optimize_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": []}}

    result = await optimize(
        {"system_forecast_number": "F1", "category": "冰箱", "target_qty": 10},
        {"build_whatif_rows": rows, "optimize": optimize_client},
    )
    assert result['response_type'] == 'optimization'
    assert set(calls[0]) == {"target_qty", "rows"}

    calls.clear()
    result = await optimize(
        {"system_forecast_number": "F1", "category": "冰箱", "target_qty": 10, "target_revenue": 1000},
        {"build_whatif_rows": rows, "optimize": optimize_client},
    )
    assert result['response_type'] == 'optimization'
    assert calls[0]["target_revenue"] == 1000


@pytest.mark.asyncio
async def test_whatif_tools_require_category_before_loading_baseline():
    async def rows(*args, **kwargs):
        raise AssertionError("category must be validated before baseline loading")

    async def upstream(body):
        raise AssertionError("category must be validated before upstream call")

    simulate_result = await simulate(
        {"system_forecast_number": "F1", "strategy_id": "discount"},
        {"build_whatif_rows": rows, "simulate": upstream},
    )
    optimize_result = await optimize(
        {"system_forecast_number": "F1", "target_qty": 10, "category": ""},
        {"build_whatif_rows": rows, "optimize": upstream},
    )

    assert simulate_result["response_type"] == "need_input"
    assert "category" in simulate_result["missing"]
    assert optimize_result["response_type"] == "need_input"
    assert "category" in optimize_result["missing"]


@pytest.mark.asyncio
async def test_whatif_tools_reject_empty_baseline_without_calling_upstream():
    calls = []

    async def rows(*args, **kwargs):
        return []

    async def upstream(body):
        calls.append(body)
        return {"status": "completed"}

    simulate_result = await simulate(
        {"system_forecast_number": "F1", "category": "冰箱", "strategy_id": "discount"},
        {"build_whatif_rows": rows, "simulate": upstream},
    )
    optimize_result = await optimize(
        {"system_forecast_number": "F1", "category": "洗衣机", "target_qty": 10},
        {"build_whatif_rows": rows, "optimize": upstream},
    )

    assert simulate_result["response_type"] == "tool_error"
    assert "F1" in simulate_result["error"]
    assert "冰箱" in simulate_result["error"]
    assert "基线为空" in simulate_result["error"]
    assert optimize_result["response_type"] == "tool_error"
    assert "F1" in optimize_result["error"]
    assert "洗衣机" in optimize_result["error"]
    assert "基线为空" in optimize_result["error"]
    assert calls == []


def test_whatif_seed_schema_requires_non_empty_category():
    for name in ("simulate", "optimize"):
        schema = TOOLS[name]["input_schema"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["category"] == {"type": "string", "minLength": 1}
        assert schema["required"] == ["system_forecast_number", "category"]


@pytest.mark.asyncio
async def test_forecast_and_explain_mock_calls():
    async def forecast(data):
        return {"status": "completed", "system_forecast_number": "F1", "forecast": [{"qty": 1}]}

    async def attribution_client(data):
        return {"factors": [{"name": "price"}]}

    async def status(task_id):
        return {"status": "completed", "task_id": task_id}

    assert (await submit_forecast({"category": "冰箱", "forecast_month": "2026-10", "horizon": 3}, {"submit_forecast": forecast}))['response_type'] == 'forecast'
    assert (await attribution({"system_forecast_number": "F1", "category": "冰箱", "sku": "S1", "period": "2026-10"}, {"get_attribution": attribution_client}))['response_type'] == 'attribution'
    assert (await task_status({"task_id": "T1"}, {"get_task_status": status}))['status'] == 'completed'
    assert (await forecast_result({"system_forecast_number": "F1", "horizon": 3}, {"get_forecast_result": forecast}))['response_type'] == 'forecast'


@pytest.mark.asyncio
async def test_submit_forecast_returns_task_metadata_and_normalizes_relative_month():
    calls = []

    async def submit(data):
        calls.append(data)
        return {
            "status": "completed",
            "system_forecast_number": "F1",
            "task_id": "T1",
            "forecast": [{"period": "2026-10", "qty": 1}],
            "top_skus": [{"sku": "SHOULD-NOT-LEAK"}],
        }

    result = await submit_forecast(
        {"category": "洗衣机", "forecast_month": "当前月", "horizon": 3},
        {
            "submit_forecast": submit,
            "default_forecast_month": True,
            "user_prompt": "预测洗衣机未来3个月销量",
        },
    )

    assert calls[0]["forecast_month"] != "当前月"
    assert result["system_forecast_number"] == "F1"
    assert result["result_ready"] is True
    assert result["next_tool"] == "get_forecast_result"
    assert "forecast" not in result
    assert "rows" not in result
    assert "top_skus" not in result
    assert "top_skus" not in result["envelope"]


@pytest.mark.asyncio
async def test_forecast_result_compacts_relay_rows_before_llm_replay():
    async def result_client(_data):
        return {
            "response_type": "forecast",
            "system_forecast_number": "F1",
            "monthly_totals": [{"period": "2026-10", "forecast_qty": 10}],
            "forecast_points": [{"period": "2026-10", "forecast_qty": 1}] * 2202,
            "top_skus": [{"sku": "S1", "series": []}],
            "envelope": {"table": {"rows": []}},
        }

    result = await forecast_result(
        {"system_forecast_number": "F1", "horizon": 3},
        {"get_forecast_result": result_client},
    )

    assert result["rows"] == result["monthly_totals"]
    assert "forecast_points" not in result
    assert "forecast_points" not in result["envelope"]
    assert result["top_skus"][0]["sku"] == "S1"


@pytest.mark.asyncio
async def test_forecast_result_marks_required_whatif_continuation_for_plan_requests():
    async def result_client(_data):
        return {
            "response_type": "forecast",
            "system_forecast_number": "F1",
            "monthly_totals": [{"period": "2026-10", "forecast_qty": 10}],
        }

    plan = await forecast_result(
        {"system_forecast_number": "F1", "horizon": 3},
        {
            "get_forecast_result": result_client,
            "user_prompt": "帮我制定冰箱下月销售计划",
        },
    )
    assert plan["workflow"] == "whatif_optimization"
    assert plan["next_tool"] == "get_whatif_strategies"
    assert plan["required_next_tools"] == ["get_whatif_strategies", "optimize"]
    assert plan["final_answer_allowed"] is False

    ordinary = await forecast_result(
        {"system_forecast_number": "F1", "horizon": 3},
        {"get_forecast_result": result_client, "user_prompt": "预测冰箱未来3个月销量"},
    )
    assert "workflow" not in ordinary


@pytest.mark.asyncio
async def test_whatif_strategy_directory_exposes_only_actionable_icewash_fields():
    async def directory(_input):
        return {
            "strategies": [
                {"id": "price_cut", "name": "降价", "status": "active", "param_kind": "ratio", "default_param": "0.9", "formula": "do not expose"},
                {"id": "gone", "name": "旧策略", "status": "disabled", "param_kind": "none"},
                {"name": "缺少 id", "status": "active"},
            ]
        }

    result = await strategies({}, {"get_whatif_strategies": directory})
    assert result["response_type"] == "whatif_strategies"
    assert result["source_tool"] == "get_whatif_strategies"
    assert result["strategies"] == [{
        "id": "price_cut",
        "name": "降价",
        "status": "active",
        "param_kind": "ratio",
        "default_param": "0.9",
    }]


@pytest.mark.asyncio
async def test_whatif_strategy_directory_does_not_hide_status_group_strategies_for_active_filter():
    calls = []

    async def directory(_input):
        calls.append(_input)
        return {
            "strategies": [
                {"id": "eol_clearance", "name": "清仓退市", "status": "eol", "param_kind": "price_pct"},
                {"id": "prelaunch", "name": "提前铺货", "status": "new", "param_kind": "none"},
            ]
        }

    result = await strategies(
        {"status": "enabled"},
        {"get_whatif_strategies": directory},
    )

    assert result["response_type"] == "whatif_strategies"
    assert {item["id"] for item in result["strategies"]} == {"eol_clearance", "prelaunch"}
    assert calls == [{"status": "enabled"}]


@pytest.mark.asyncio
async def test_optimize_defaults_targets_from_full_baseline_summary():
    calls = []

    async def baseline(*args, **kwargs):
        return {
            "source": "db",
            "rows": [{"sku": "A", "baseline_qty": 120, "baseline_price": 10, "details": []}],
            "summary": {
                "baseline_qty": 120,
                "baseline_amount": 1200,
                "price_coverage_qty": 1,
                "price_status": "complete",
            },
        }

    async def optimize_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": []}}

    result = await optimize(
        {"system_forecast_number": "F1", "category": "冰箱"},
        {"load_whatif_baseline": baseline, "optimize": optimize_client},
    )
    assert result["response_type"] == "optimization"
    assert calls[0]["target_qty"] == 80_000
    assert calls[0]["target_revenue"] == 50_000_000
    assert result["meta"]["target_source"] == {"qty": "default_workbench", "revenue": "default_workbench"}
    assert result["meta"]["goal_vs_baseline"]["qty"]["gap"] == 79_880
    assert result["meta"]["baseline_summary"]["price_status"] == "complete"


@pytest.mark.asyncio
async def test_optimize_uses_explicit_targets_from_user_prompt_when_model_omits_fields():
    calls = []

    async def baseline(*args, **kwargs):
        return {
            "source": "db",
            "rows": [{"sku": "A", "baseline_qty": 120, "baseline_price": 10, "details": []}],
            "summary": {
                "baseline_qty": 120,
                "baseline_amount": 1200,
                "price_coverage_qty": 1,
                "price_status": "complete",
            },
        }

    async def optimize_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": []}}

    result = await optimize(
        {"system_forecast_number": "F1", "category": "冰箱"},
        {
            "load_whatif_baseline": baseline,
            "optimize": optimize_client,
            "user_prompt": "帮我制定冰箱下月销售计划，目标销量 4 万台，目标销售额 500 万元",
        },
    )
    assert calls[0]["target_qty"] == 40_000
    assert calls[0]["target_revenue"] == 5_000_000
    assert result["meta"]["target_source"] == {"qty": "user_prompt", "revenue": "user_prompt"}
    assert result["meta"]["goal_vs_baseline"]["qty"]["gap"] == 39_880
    assert result["meta"]["goal_vs_baseline"]["revenue"]["gap"] == 4_998_800


@pytest.mark.asyncio
async def test_simulate_maps_chinese_strategy_and_keeps_unmatched_rows_maintain():
    calls = []

    async def directory(_input):
        return {
            "strategies": [
                {"id": "price_cut", "name": "降价促销", "param_kind": "price_pct", "default_param": "-8%"},
                {"id": "maintain", "name": "维持现状", "param_kind": "none", "default_param": ""},
            ]
        }

    async def rows(*args, **kwargs):
        return [
            {"sku": "A", "series": "主销系列", "status": "主销", "baseline_qty": 10},
            {"sku": "B", "series": "新品系列", "status": "新品", "baseline_qty": 20},
        ]

    async def simulate_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": body["rows"]}}

    result = await simulate(
        {
            "system_forecast_number": "F1",
            "category": "冰箱",
            "strategy_id": "降价促销",
            "series": "主销系列",
        },
        {
            "get_whatif_strategies": directory,
            "build_whatif_rows": rows,
            "simulate": simulate_client,
        },
    )
    assert result["response_type"] == "simulation"
    payload_rows = calls[0]["rows"]
    assert payload_rows[0]["strategy_id"] == "price_cut"
    assert payload_rows[0]["param"] == "-8%"
    assert payload_rows[1]["strategy_id"] == "maintain"
    assert payload_rows[1]["param"] is None
    assert result["meta"]["matched_rows"] == 1
    assert result["meta"]["unmatched_rows"] == 1


@pytest.mark.asyncio
async def test_simulate_missing_strategy_returns_directory_candidates_without_model_call():
    calls = []

    async def directory(_input):
        return {"strategies": [{"id": "price_cut", "name": "降价促销"}, {"id": "maintain", "name": "维持现状"}]}

    async def upstream(body):
        calls.append(body)
        return {"status": "completed"}

    result = await simulate(
        {"system_forecast_number": "F1", "category": "冰箱"},
        {"get_whatif_strategies": directory, "simulate": upstream},
    )
    assert result["response_type"] == "need_input"
    assert result["missing"] == ["strategy_id"]
    assert result["candidates"] == ["price_cut", "maintain"]
    assert calls == []


def test_forecast_payload_is_sorted_and_top5_is_forecast_driven():
    from types import SimpleNamespace

    rows = [
        SimpleNamespace(id=1, category="冰箱", horizon="N+2", forecast_month="2026-11-01", sku="A", final_value=50),
        SimpleNamespace(id=2, category="冰箱", horizon="N+1", forecast_month="2026-10-01", sku="B", final_value=40),
        SimpleNamespace(id=3, category="冰箱", horizon="N+1", forecast_month="2026-10-01", sku="A", final_value=30),
        SimpleNamespace(id=4, category="冰箱", horizon="N+3", forecast_month="2026-12-01", sku="C", final_value=100),
        SimpleNamespace(id=5, category="冰箱", horizon="N+10", forecast_month="2027-07-01", sku="Z", final_value=999),
    ]
    result = _forecast_payload(rows, version="F1", category="冰箱", horizon=3)
    assert [point["horizon"] for point in result["forecast"]] == ["N+1", "N+1", "N+2", "N+3"]
    assert all({"source_tool", "system_forecast_number", "category", "horizon", "period", "sku", "forecast_qty"} <= point.keys() for point in result["forecast"])
    assert result["category_total"] == 220.0
    assert [(item["rank"], item["sku"], item["forecast_qty"]) for item in result["top_skus"]] == [
        (1, "C", 100.0),
        (2, "A", 80.0),
        (3, "B", 40.0),
    ]
    assert [item["period"] for item in result["top_skus"][1]["series"]] == ["2026-10", "2026-11"]


@pytest.mark.asyncio
async def test_forecast_horizon_defaults_without_guessing_required_inputs():
    calls = []

    async def forecast(data):
        calls.append(data)
        return {"status": "completed", "system_forecast_number": "F1", "forecast": []}

    result = await submit_forecast(
        {"category": "冰箱", "forecast_month": "2026-10"},
        {"submit_forecast": forecast},
    )
    assert result["response_type"] == "forecast"
    assert calls[0]["horizon"] == 3
    assert (await submit_forecast({"category": "冰箱"}))["missing"] == ["forecast_month"]
