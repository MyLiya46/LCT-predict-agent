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
    "你是销售预测与冰洗经营分析助手。只通过已注册的能力工具完成工作，"
    "不要输出 intent、planner action，不要编写正则分类，也不要虚构任何模型数字。"
    "工作流约束必须严格遵守：用户说历史、过去、实际销售或近半年实际销量时，只调用 get_history，"
    "不得调用 submit_forecast、get_forecast_result 或 get_attribution；用户说预测、未来、趋势预测或未来 N 个月时，"
    "先调用 submit_forecast，再用返回的 system_forecast_number 调用 get_forecast_result，绝不能用 get_history 代替预测。"
    "普通预测读取 get_forecast_result 后即可结束，不得因为结果中存在排名字段就展示 TOP5。"
    "用户要求预测并分析、TOP5 型号趋势、主要原因或归因时，读取 get_forecast_result 后不得直接结束；"
    "必须只从返回的 top_skus 前 5 个型号中逐一调用 get_attribution（预测期首月或用户明确指定的 period），"
    "完成归因后才能回答，同时引用预测量/排名和真实归因因子，绝不能凭排名字段编造原因。"
    "用户要求制定销售计划或推荐最佳策略时，先确定 What-if 预测基线：没有可复用的预测版本时先调用 submit_forecast（下月计划按工作台 N+1…N+6 口径），"
    "再用返回版本调用 get_forecast_result；随后必须调用 get_whatif_strategies 读取有限策略目录，最后调用 optimize。"
    "特别是用户原话‘帮我制定冰箱下月销售计划’绝不是普通预测：get_forecast_result 返回后禁止直接回答，必须继续 get_whatif_strategies，再调用 optimize。"
    "用户语义明确给出目标销量/销售额时，分别按 target_qty（台）/target_revenue（元）传入；‘4 万台’应传 40000，‘500 万元’应传 5000000。"
    "用户没有给目标时不要追问，也不要臆造用户目标，省略可选目标字段，让 optimize 使用工作台默认目标；optimize 会读取完整 baseline，比较目标与 baseline 差距，"
    "在有限策略目录内搜索推荐方案并返回 baseline/target/simulated 结构化结果。收到 optimize 结果后再汇总报告，必须说明目标来源、目标与 baseline 差距、推荐策略、模拟结果和数据缺失状态。"
    "如果调整某策略之后会怎样调用 simulate；get_attribution 只做白盒归因，不能承担策略优化。"
    "What-if 需要先调用 get_whatif_strategies，只能使用目录返回的 id、name、status、param_kind、default_param，"
    "不得臆造 strategy_id 或自由文本策略。缺少 category 或 forecast_month 时分别返回 need_input(category) 或 need_input(forecast_month)，"
    "不要猜测品类、SKU 或任务结果；用户说‘未来/下月/未来 N 个月’但未写基准月时，"
    "submit_forecast 默认使用下一个自然月；只有无法确定品类或月份时才返回 need_input。普通预测未给 horizon 时使用 3。"
)


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS = {
    "get_history": {
        "description": "仅查询过去/历史/实际销售销量；历史问题只能使用此工具，不能用它回答未来预测。",
        "input_schema": _schema(
            {
                "category": {"type": "string"}, "sku": {"type": "string"}, "channel": {"type": "string"},
                "start": {"type": "string"}, "end": {"type": "string"},
            }, ["category"],
        ),
        "output_schema": {"type": "object"},
    },
    "submit_forecast": {
        "description": "发起未来预测。预测/未来问题必须先调用本工具，再用返回的 system_forecast_number 调用 get_forecast_result；forecast_month 省略时默认下一个自然月，horizon 省略时默认 3。",
        "input_schema": _schema({"category": {"type": "string", "minLength": 1}, "forecast_month": {"type": "string", "minLength": 1}, "horizon": {"type": "integer", "minimum": 1, "maximum": 12, "default": 3}}, ["category"]),
        "output_schema": {"type": "object"},
    },
    "get_task_status": {
        "description": "查询已有预测任务状态；不能替代 submit_forecast 或 get_forecast_result。",
        "input_schema": _schema({"task_id": {"type": "string"}}, ["task_id"]),
        "output_schema": {"type": "object"},
    },
    "get_forecast_result": {
        "description": "查询 submit_forecast 返回版本的结构化未来预测点、品类总量和按累计 forecast_qty 排序的 TOP5；不得从历史销量替代预测值。若原问题是‘制定销售计划/推荐策略’，本工具返回后不能结束，必须继续 get_whatif_strategies → optimize。",
        "input_schema": _schema({"system_forecast_number": {"type": "string", "minLength": 1}, "horizon": {"type": "integer", "minimum": 1, "maximum": 12, "default": 3}}, ["system_forecast_number"]),
        "output_schema": {"type": "object"},
    },
    "get_attribution": {
        "description": "查询一个预测版本中一个 TOP5 SKU 的白盒归因；period 可省略，默认预测期首月，显式 period 优先，返回预测值和因子证据。",
        "input_schema": _schema({"system_forecast_number": {"type": "string", "minLength": 1}, "category": {"type": "string", "minLength": 1}, "sku": {"type": "string", "minLength": 1}, "period": {"type": "string"}}, ["system_forecast_number", "category", "sku"]),
        "output_schema": {"type": "object"},
    },
    "simulate": {
        "description": "对已有预测基线执行“如果调整某策略之后会怎样”的 What-if 模拟；strategy_id 缺失时先读取 get_whatif_strategies，且只能使用目录中的策略 id。",
        "input_schema": _schema({"system_forecast_number": {"type": "string"}, "category": {"type": "string", "minLength": 1}, "strategy_id": {"type": "string"}, "strategy_name": {"type": "string"}, "param": {}, "traffic_tier": {"type": "string"}, "sku": {}, "series": {}, "status": {}, "filters": {"type": "object"}}, ["system_forecast_number", "category"]),
        "output_schema": {"type": "object"},
    },
    "optimize": {
        "description": "对已有预测基线制定计划/推荐有限策略；target_qty 单位为台、target_revenue 单位为元，缺省时使用工作台默认目标；策略参数必须来自 get_whatif_strategies，不能由模型臆造。",
        "input_schema": _schema({"system_forecast_number": {"type": "string"}, "category": {"type": "string", "minLength": 1}, "target_qty": {"type": "number", "minimum": 0, "description": "目标销量（台）"}, "target_revenue": {"type": "number", "minimum": 0, "description": "目标销售额（元）"}, "param": {}, "traffic_tier": {"type": "string"}}, ["system_forecast_number", "category"]),
        "output_schema": {"type": "object"},
    },
    "get_whatif_strategies": {
        "description": "读取 icewash 有效 What-if 策略目录；只能从返回的 id/name/status/param_kind/default_param 中选择策略。",
        "input_schema": _schema({"status": {"type": "string"}}, []),
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
            execution = {
                "kind": "internal",
                "handler": name,
                "timeout_s": 300 if name == "submit_forecast" else (30 if name == "get_whatif_strategies" else 120),
            }
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
