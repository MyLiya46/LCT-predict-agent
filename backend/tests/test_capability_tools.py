from __future__ import annotations

import pytest

from app.tools.internal.get_attribution.tool import handle as attribution
from app.tools.internal.get_forecast_result.tool import handle as forecast_result
from app.tools.internal.get_history.tool import handle as history
from app.tools.internal.get_task_status.tool import handle as task_status
from app.tools.internal.optimize.tool import handle as optimize
from app.tools.internal.simulate.tool import handle as simulate
from app.tools.internal.submit_forecast.tool import handle as submit_forecast


@pytest.mark.asyncio
async def test_capabilities_need_input_and_response_types():
    assert (await history({}))['response_type'] == 'need_input'
    assert (await submit_forecast({}))['response_type'] == 'need_input'
    assert (await attribution({}))['response_type'] == 'need_input'

    async def rows(*args, **kwargs):
        return [{"sku": "S1", "baseline_qty": 2}]

    calls = []

    async def simulate_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": []}}

    result = await simulate(
        {"system_forecast_number": "F1", "strategy_id": "discount", "param": {"x": 1}},
        {"build_whatif_rows": rows, "simulate": simulate_client},
    )
    assert result['response_type'] == 'simulation'
    assert set(calls[0]) == {"strategy_id", "param", "rows"}

    calls.clear()

    async def optimize_client(body):
        calls.append(body)
        return {"status": "completed", "result": {"rows": []}}

    result = await optimize(
        {"system_forecast_number": "F1", "target_qty": 10},
        {"build_whatif_rows": rows, "optimize": optimize_client},
    )
    assert result['response_type'] == 'optimization'
    assert set(calls[0]) == {"target_qty", "rows"}


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
