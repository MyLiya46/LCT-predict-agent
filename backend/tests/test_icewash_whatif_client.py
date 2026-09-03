from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.services.icewash_whatif_client import IcewashWhatifClient, IcewashWhatifError


@pytest.mark.asyncio
@respx.mock
async def test_proxy_paths_and_payloads():
    base = "http://127.0.0.1:8001"
    respx.get(f"{base}/whatif/strategies").mock(return_value=Response(200, json={"strategies": [{}], "traffic_tiers": [], "total": 8}))
    simulate = respx.post(f"{base}/simulate").mock(return_value=Response(200, json={"task_id": "sim-1", "status": "pending"}))
    respx.post(f"{base}/optimize").mock(return_value=Response(200, json={"task_id": "opt-1", "status": "pending"}))
    respx.get(f"{base}/tasks/task-1").mock(return_value=Response(200, json={"status": "completed", "progress": "done", "result": {}, "error_message": None}))
    client = IcewashWhatifClient(base, retry_delay=0)
    assert (await client.strategies())["total"] == 8
    body = {"strategy_id": "maintain", "param": None, "traffic_tier": None, "rows": [{"sku": "A"}]}
    assert (await client.simulate(body))["task_id"] == "sim-1"
    assert simulate.calls[0].request.content == b'{"strategy_id":"maintain","param":null,"traffic_tier":null,"rows":[{"sku":"A"}]}'
    assert (await client.optimize({"target_qty": 10, "param": None, "traffic_tier": None, "rows": []}))["task_id"] == "opt-1"
    assert (await client.task_status("task-1"))["status"] == "completed"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_retries_three_times_and_maps_failure():
    route = respx.get("http://127.0.0.1:8001/whatif/strategies").mock(return_value=Response(503, json={"detail": "down"}))
    client = IcewashWhatifClient(retry_delay=0)
    with pytest.raises(IcewashWhatifError):
        await client.strategies()
    assert route.call_count == 3
