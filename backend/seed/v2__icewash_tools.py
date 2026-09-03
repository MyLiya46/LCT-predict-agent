"""Idempotent registration of the backup-native icewash chat capabilities."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import Scenario, Tool
from app.tools.validate import validate_execution, validate_tool_schema

logger = logging.getLogger("seed.icewash_tools")
SEED_ADVISORY_LOCK_ID = 99102027

SYSTEM_PROMPT = (
    "你是销售预测与冰洗经营分析助手。请直接依据工具 schema 选择能力工具，"
    "不要输出 intent、planner action，也不要虚构模型结果。使用 get_history 查询历史，"
    "submit_forecast 发起预测，get_attribution 获取归因，simulate/optimize 提交 what-if；"
    "get_task_status/get_forecast_result 只用于查询已有任务。缺少必填参数时向用户询问，"
    "不要猜测品类、月份、SKU 或任务结果。"
)


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS = {
    "get_history": {
        "description": "查询冰洗历史销量数据。",
        "input_schema": _schema(
            {
                "category": {"type": "string"}, "sku": {"type": "string"}, "channel": {"type": "string"},
                "start": {"type": "string"}, "end": {"type": "string"},
            }, ["category"],
        ),
        "output_schema": {"type": "object"},
    },
    "submit_forecast": {
        "description": "提交冰洗预测并等待最终预测结果。",
        "input_schema": _schema({"category": {"type": "string"}, "forecast_month": {"type": "string"}, "horizon": {"type": "integer", "minimum": 1, "maximum": 12}}, ["category", "forecast_month", "horizon"]),
        "output_schema": {"type": "object"},
    },
    "get_task_status": {
        "description": "查询已有预测任务状态。",
        "input_schema": _schema({"task_id": {"type": "string"}}, ["task_id"]),
        "output_schema": {"type": "object"},
    },
    "get_forecast_result": {
        "description": "查询已有预测版本的结果。",
        "input_schema": _schema({"system_forecast_number": {"type": "string"}, "horizon": {"type": "integer", "minimum": 1, "maximum": 12}}, ["system_forecast_number", "horizon"]),
        "output_schema": {"type": "object"},
    },
    "get_attribution": {
        "description": "查询预测归因因子。",
        "input_schema": _schema({"system_forecast_number": {"type": "string"}, "category": {"type": "string"}, "sku": {"type": "string"}, "period": {"type": "string"}}, ["system_forecast_number", "category", "sku", "period"]),
        "output_schema": {"type": "object"},
    },
    "simulate": {
        "description": "提交基于预测基线的策略模拟。",
        "input_schema": _schema({"system_forecast_number": {"type": "string"}, "strategy_id": {"type": "string"}, "param": {}, "traffic_tier": {"type": "string"}}, ["system_forecast_number", "strategy_id"]),
        "output_schema": {"type": "object"},
    },
    "optimize": {
        "description": "提交基于预测基线的目标量优化。",
        "input_schema": _schema({"system_forecast_number": {"type": "string"}, "target_qty": {"type": "number"}, "param": {}, "traffic_tier": {"type": "string"}}, ["system_forecast_number", "target_qty"]),
        "output_schema": {"type": "object"},
    },
}


async def _advisory_lock(session: AsyncSession) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect == "postgresql":
        await session.execute(text(f"SELECT pg_advisory_xact_lock({SEED_ADVISORY_LOCK_ID})"))


async def run_seed(session: AsyncSession | None = None) -> None:
    if session is None:
        async with get_session_factory()() as managed:
            await run_seed(managed)
        return
    async with session.begin():
        await _advisory_lock(session)
        scenario = (await session.execute(select(Scenario).where(Scenario.code == "sales_query_predict"))).scalars().first()
        if scenario is None:
            scenario = Scenario(code="sales_query_predict", name="销售查询预测", model_ref={"provider_id": None, "model": ""}, system_prompt=SYSTEM_PROMPT, enabled=True)
            session.add(scenario)
            await session.flush()
        else:
            scenario.system_prompt = SYSTEM_PROMPT
        for name, spec in TOOLS.items():
            validate_tool_schema(spec["input_schema"], spec["output_schema"])
            execution = {"kind": "internal", "handler": name, "timeout_s": 300 if name == "submit_forecast" else 120}
            validate_execution(execution)
            row = (await session.execute(select(Tool).where(Tool.name == name))).scalars().first()
            if row is None:
                row = Tool(name=name, scenario_id=scenario.id)
                session.add(row)
            row.description = spec["description"]
            row.input_schema = spec["input_schema"]
            row.output_schema = spec["output_schema"]
            row.execution = execution
            row.status = "enabled"
            row.scenario_id = scenario.id
        await session.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
