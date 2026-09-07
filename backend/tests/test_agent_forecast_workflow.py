from __future__ import annotations

import copy
import json
import uuid

import pytest
from sqlalchemy import select

from app.engine.flow import ActiveFlowRegistry
from app.engine.loop import RunContext, run_flow
from app.llm.events import ContentDeltaEvent, DoneReasonEvent, ToolCall, ToolCallBatchEvent
from app.models import Conversation, Message, Scenario, User
from app.sse.hub import Hub
from seed.v2__icewash_tools import run_seed as run_icewash_seed


class WorkflowProvider:
    """Deterministic multi-round provider for the T31 tool workflow."""

    default_model = "workflow-mock"
    provider_id = "workflow-mock"

    def __init__(self) -> None:
        self.chat_messages: list[list[dict]] = []
        self.tool_call_rounds: list[list[str]] = []

    @staticmethod
    def _tool_outputs(messages: list[dict]) -> list[tuple[str, dict]]:
        outputs = []
        for message in messages:
            if message.get("role") != "tool":
                continue
            payload = json.loads(message["content"])
            result = payload.get("result", {})
            outputs.append((payload.get("tool_name", ""), result.get("output", {})))
        return outputs

    async def chat(self, messages, tools=None, config=None):
        snapshot = copy.deepcopy(messages)
        self.chat_messages.append(snapshot)
        text = "".join(str(item.get("content", "")) for item in messages if item.get("role") == "user")
        mode = "top5" if "TOP5" in text.upper() else ("history" if "历史" in text or "过去" in text else "forecast")
        previous = self._tool_outputs(messages)
        names = [name for name, _output in previous]

        if mode == "history" and not previous:
            calls = [ToolCall(index=0, id="history-1", name="get_history", arguments={"category": "冰箱"})]
        elif mode == "forecast" and not previous:
            calls = [ToolCall(index=0, id="submit-1", name="submit_forecast", arguments={"category": "冰箱", "forecast_month": "2026-10"})]
        elif mode == "forecast" and names[-1:] == ["submit_forecast"]:
            calls = [ToolCall(index=0, id="result-1", name="get_forecast_result", arguments={"system_forecast_number": "F1"})]
        elif mode == "top5" and not previous:
            calls = [ToolCall(index=0, id="submit-top5", name="submit_forecast", arguments={"category": "冰箱", "forecast_month": "2026-10"})]
        elif mode == "top5" and names[-1:] == ["submit_forecast"]:
            calls = [ToolCall(index=0, id="result-top5", name="get_forecast_result", arguments={"system_forecast_number": "F1"})]
        elif mode == "top5" and names[-1:] == ["get_forecast_result"]:
            forecast = previous[-1][1]
            calls = [
                ToolCall(
                    index=index,
                    id=f"attr-{index}",
                    name="get_attribution",
                    arguments={"system_forecast_number": "F1", "category": "冰箱", "sku": item["sku"], "period": item["series"][0]["period"]},
                )
                for index, item in enumerate(forecast.get("top_skus", []), start=1)
            ]
        else:
            if mode == "history":
                reply = "历史证据 9999"
            elif mode == "top5":
                forecast_qty = next((output.get("forecast_qty") for name, output in previous if name == "get_forecast_result"), 0)
                attribution_qty = next((output.get("y_pred") for name, output in previous if name == "get_attribution"), 0)
                reply = f"预测证据 {forecast_qty}；归因证据 {attribution_qty}"
            else:
                forecast_qty = next((output.get("forecast_qty") for name, output in previous if name == "get_forecast_result"), 0)
                reply = f"预测证据 {forecast_qty}"
            for chunk in (reply[index : index + 8] for index in range(0, len(reply), 8)):
                yield ContentDeltaEvent(text=chunk)
            yield DoneReasonEvent(stop_reason="stop", final_text=reply)
            return

        self.tool_call_rounds.append([call.name for call in calls])
        yield ToolCallBatchEvent(calls=calls)
        yield DoneReasonEvent(stop_reason="tool_use", final_text="")

    async def complete(self, messages, config=None) -> str:
        return "[]"


def _forecast_output(source_tool: str) -> dict:
    top_skus = [
        {"rank": 1, "sku": "S1", "forecast_qty": 90, "series": [{"period": "2026-10", "forecast_qty": 45}]},
        {"rank": 2, "sku": "S2", "forecast_qty": 80, "series": [{"period": "2026-10", "forecast_qty": 40}]},
        {"rank": 3, "sku": "S3", "forecast_qty": 70, "series": [{"period": "2026-10", "forecast_qty": 35}]},
        {"rank": 4, "sku": "S4", "forecast_qty": 35, "series": [{"period": "2026-10", "forecast_qty": 18}]},
        {"rank": 5, "sku": "S5", "forecast_qty": 25, "series": [{"period": "2026-10", "forecast_qty": 12}]},
    ]
    return {
        "response_type": "forecast",
        "source_tool": source_tool,
        "system_forecast_number": "F1",
        "category": "冰箱",
        "horizon": 3,
        "forecast_qty": 300,
        "forecast": [{"source_tool": source_tool, "system_forecast_number": "F1", "category": "冰箱", "horizon": "N+1", "period": "2026-10", "sku": "S1", "forecast_qty": 45}],
        "top_skus": top_skus,
    }


async def _prepare(factory):
    async with factory() as session:
        await run_icewash_seed(session)
        scenario = (await session.execute(select(Scenario).where(Scenario.code == "sales_query_predict"))).scalars().one()
        user = User(email=f"t31-{uuid.uuid4().hex[:10]}@corp.com", password_hash="H", nickname="T31")
        session.add(user)
        await session.flush()
        conversation = Conversation(owner_id=user.id, title="T31 workflow")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role="assistant", content="", status="running", trace_id=str(uuid.uuid4()))
        session.add(message)
        await session.commit()
        return str(conversation.id), str(message.id), scenario


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_rounds"),
    [
        ("查询历史冰箱销量", [["get_history"]]),
        ("预测冰箱未来 3 个月销量", [["submit_forecast"], ["get_forecast_result"]]),
        ("预测冰箱未来 3 个月 TOP5 型号趋势并分析", [["submit_forecast"], ["get_forecast_result"], ["get_attribution"] * 5]),
    ],
)
async def test_agent_forecast_workflow_never_replaces_forecast_with_history(db_session_factory, monkeypatch, prompt, expected_rounds):
    import app.engine.loop as loop_module

    provider = WorkflowProvider()

    async def resolve_provider(*_args, **_kwargs):
        return provider

    async def execute_tools(_session, _ctx, tool_calls, _tools):
        results = []
        for call in tool_calls:
            if call.name == "get_history":
                output = {"response_type": "history", "source_tool": "get_history", "rows": [{"period": "2026-09", "qty": 9999}]}
            elif call.name in {"submit_forecast", "get_forecast_result"}:
                output = _forecast_output(call.name)
            elif call.name == "get_attribution":
                output = {"response_type": "attribution", "source_tool": "get_attribution", "system_forecast_number": "F1", "category": "冰箱", "period": call.arguments["period"], "sku": call.arguments["sku"], "y_pred": 11, "qty_lag1": 9, "factors": [{"name": "价格", "impact": 2}]}
            else:
                output = {"response_type": "tool_error", "error": f"unexpected {call.name}"}
            results.append({"ok": True, "output": output, "error": None, "duration_ms": 0, "request_id": call.id})
        return results

    monkeypatch.setattr(loop_module, "_resolve_provider", resolve_provider)
    monkeypatch.setattr(loop_module, "_execute_tools_parallel", execute_tools)
    factory = db_session_factory
    conversation_id, message_id, scenario = await _prepare(factory)
    registry = ActiveFlowRegistry()
    flow = await registry.register(conversation_id)
    try:
        async with factory() as session:
            trace_id = str((await session.get(Message, message_id)).trace_id)
        result = await run_flow(
            RunContext(
                conversation_id=conversation_id,
                message_id=message_id,
                trace_id=trace_id,
                scenario=scenario,
                user_id="t31@corp.com",
                flow=flow,
                hub=__import__("app.sse.hub", fromlist=["Hub"]).Hub(),
                session_factory=factory,
            ),
            prompt,
            factory,
        )
    finally:
        await registry.release(conversation_id)

    assert result["status"] == "completed", result
    assert provider.tool_call_rounds == expected_rounds
    flat_names = [name for names in provider.tool_call_rounds for name in names]
    if "历史" in prompt:
        assert flat_names == ["get_history"]
        assert "submit_forecast" not in flat_names and "get_forecast_result" not in flat_names
    elif "TOP5" in prompt:
        assert flat_names[:2] == ["submit_forecast", "get_forecast_result"]
        assert flat_names.count("get_attribution") == 5
        tool_messages = [message for message in provider.chat_messages[-1] if message.get("role") == "tool"]
        evidence = [json.loads(message["content"])["result"]["output"] for message in tool_messages]
        assert any(item.get("source_tool") == "get_forecast_result" and item.get("forecast_qty") == 300 for item in evidence)
        assert sum(1 for item in evidence if item.get("source_tool") == "get_attribution") == 5
        assert result["final_text"] == "预测证据 300；归因证据 11"
        assert "9999" not in result["final_text"]
    else:
        assert flat_names == ["submit_forecast", "get_forecast_result"]
        assert result["final_text"] == "预测证据 300"
