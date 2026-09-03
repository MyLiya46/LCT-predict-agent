"""Agent 执行循环（T16 / tech_design §3.4 伪码）。

LLM 规划 → 工具并行执行 → 结果回灌 → 重试/降级 → 中断 SafePoint → checkpoint → 最终回复。
事件全程写 message_event(trace) + 经 sse hub 推送。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config_service import get_sys_config
from app.engine.checkpoint import save_checkpoint
from app.engine.flow import FlowControl
from app.engine.retry import (
    MAX_LLM_RETRIES,
    backoff_delay,
    llm_error_retryable,
    tool_error_retryable,
)
from app.engine.state import EngineState, MessageStatus
from app.models import Message, Tool
from app.sandbox import client as sandbox_client
from app.sandbox.lifecycle import record_finish, record_start
from app.sse.events import EVT_FOLLOW_UP, SsePayload
from app.sse.hub import Hub
from app.tools.dashboard_spec import DASHBOARD_TOOL_NAMES as _DASHBOARD_TOOL_NAMES
from app.tools.dashboard_spec import build_dashboard_spec as _build_dashboard_spec
from app.tracing.trace import (
    AGENT_PROCESS,
    DONE,
    TOOL_CALL,
    TOOL_ERROR,
    TOOL_RESULT,
    append_event,
)

logger = logging.getLogger("app.engine")

# A cold forecast task can take longer than the default sandbox-style tool
# timeout.  The model client still has its own poll deadline; this is only the
# maximum time the chat turn is willing to wait for a synchronous forecast.
FORECAST_TOOL_TIMEOUT_S = 300


@dataclass
class ToolExecutionContext:
    call_id: str
    tool: Tool
    input_data: dict[str, Any]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class RunContext:
    conversation_id: str
    message_id: str
    trace_id: str
    scenario: Any
    user_id: str
    flow: FlowControl
    hub: Hub
    session_factory: async_sessionmaker[AsyncSession]
    # Request-scoped OAuth context.  These values are intentionally not part
    # of Conversation/Message/Event and are only made available to the
    # provider for this execution.
    oa: str | None = None
    oauth_access_token: str | None = None


def _make_tool_message(tool_name: str, call_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """工具结果回灌 message（OpenAI tool role 格式）。"""
    content = {
        "tool_call_id": call_id,
        "tool_name": tool_name,
        "result": result,
    }
    return {
        "role": "tool",
        "content": __import__("json").dumps(content, ensure_ascii=False),
        "tool_call_id": call_id,
    }


async def _emit_agent_state(
    session: AsyncSession, ctx: RunContext, state: str, detail: Optional[str] = None
) -> None:
    seq = await append_event(
        session,
        trace_id=ctx.trace_id,
        message_id=ctx.message_id,
        type=AGENT_PROCESS,
        payload={"state": state, **({"detail": detail} if detail else {})},
    )
    await ctx.hub.publish(ctx.conversation_id, "agent.process", {"state": state, **({"detail": detail} if detail else {})}, seq)
    await ctx.hub.publish(ctx.conversation_id, "agent.status", {"state": state})


async def _emit_content_delta(ctx: RunContext, text: str) -> None:
    await ctx.hub.publish(ctx.conversation_id, "message.delta", {"text": text})


async def _execute_one_tool(
    session: AsyncSession,
    ctx: RunContext,
    tctx: ToolExecutionContext,
    max_concurrent: int,
) -> dict[str, Any]:
    """执行单个工具调用（含生命周期记录 + 事件）。"""
    tool = tctx.tool
    execution = tool.execution or {}
    # T43：internal 工具进程内执行（不走 daemon、不写 sandbox_instances）
    if execution.get("kind") == "internal":
        return await _execute_internal_tool(session, ctx, tctx, execution)
    # 数据源凭据：从绑定的数据源取 env 注入清单
    from app.models import DataSource

    ds_creds: dict[str, str] = {}
    for alias in execution.get("env_from_datasource", []):
        ds_row = (
            await session.execute(__import__("sqlalchemy").select(DataSource).where(DataSource.name == alias))
        ).scalars().first()
        if ds_row is not None:
            from app.datasource.service import prepare_env

            ds_creds.update(prepare_env(ds_row))

    call_seq = await append_event(
        session,
        trace_id=ctx.trace_id,
        message_id=ctx.message_id,
        type=TOOL_CALL,
        payload={
            "name": tool.name,
            "input": tctx.input_data,
            "plan_index": 0,
            "request_id": tctx.request_id,
        },
    )
    await ctx.hub.publish(
        ctx.conversation_id, "tool.call",
        {"name": tool.name, "input": tctx.input_data, "plan_index": 0, "request_id": tctx.request_id},
        call_seq,
    )

    inst = await record_start(
        session,
        tool_id=str(tool.id),
        trace_id=ctx.trace_id,
        message_id=ctx.message_id,
        request_id=tctx.request_id,
        image=execution.get("image"),
    )

    retries = 0
    max_tool_retries = execution.get("max_retries", 2)
    while True:
        result = await sandbox_client.execute(
            execution,
            ds_creds,
            tctx.input_data,
            tctx.request_id,
            timeout_s=execution.get("timeout_s"),
        )
        if result.ok or retries >= max_tool_retries or not tool_error_retryable(result.error_code):
            break
        retries += 1
        detail = f"{tool.name} 失败 {result.error_code}，重试 {retries}/{max_tool_retries}"
        await _emit_agent_state(session, ctx, EngineState.RETRYING, detail)
        await asyncio.sleep(backoff_delay(retries))

    await session.flush()
    if result.ok:
        await record_finish(
            session, inst, status="completed",
            container_id=result.container_id, reused_warm=result.reused_warm, exit_code=result.exit_code,
        )
        # 【变更自 T43】确定性看板触发：query/predict 成功且返回数据 → 自动附看板 spec
        # （不依赖 AI 判断、不额外调 LLM；正常聊天不调这两个工具则无 spec → 前端不渲染）
        dashboard_spec: dict[str, Any] | None = None
        if tool.name in _DASHBOARD_TOOL_NAMES:
            dashboard_spec = _build_dashboard_spec(tool.name, result.output)

        result_payload: dict[str, Any] = {
            "name": tool.name,
            "output": result.output,
            "duration_ms": result.duration_ms,
            "status": "ok",
        }
        if dashboard_spec is not None:
            result_payload["dashboard_spec"] = dashboard_spec

        result_seq = await append_event(
            session,
            trace_id=ctx.trace_id,
            message_id=ctx.message_id,
            type=TOOL_RESULT,
            payload=result_payload,
        )
        sse_payload: dict[str, Any] = {
            "name": tool.name,
            "output_summary": _summarize(result.output),
            "duration_ms": result.duration_ms,
            "status": "ok",
        }
        if dashboard_spec is not None:
            sse_payload["dashboard_spec"] = dashboard_spec
        await ctx.hub.publish(ctx.conversation_id, "tool.result", sse_payload, result_seq)
    else:
        await record_finish(
            session, inst, status="timeout" if result.error_code == "TIMEOUT" else "error",
            container_id=result.container_id, reused_warm=result.reused_warm, exit_code=result.exit_code,
        )
        err_seq = await append_event(
            session,
            trace_id=ctx.trace_id,
            message_id=ctx.message_id,
            type=TOOL_ERROR,
            payload={
                "name": tool.name,
                "error_code": result.error_code,
                "message": result.message,
                "retried": retries,
            },
        )
        await ctx.hub.publish(
            ctx.conversation_id, "tool.error",
            {"name": tool.name, "error_code": result.error_code, "message": result.message, "retried": retries},
            err_seq,
        )
    return result.to_dict()


async def _execute_internal_tool(
    session: AsyncSession,
    ctx: RunContext,
    tctx: ToolExecutionContext,
    execution: dict[str, Any],
) -> dict[str, Any]:
    """T43：internal 工具进程内执行，归一为与 sandbox 相同的 ToolExecutionResult 语义。

    - 事件：tool_call / tool_result / tool_error 照常，追溯/审计复用；
    - 不写 sandbox_instances（无容器生命周期）；
    - render_dashboard 输出为 spec（全文透传，_summarize 不截断——直接以 spec 形式返回）。
    """
    from app.tools.internal import run_internal

    tool = tctx.tool
    call_seq = await append_event(
        session,
        trace_id=ctx.trace_id,
        message_id=ctx.message_id,
        type=TOOL_CALL,
        payload={
            "name": tool.name,
            "input": tctx.input_data,
            "plan_index": 0,
            "request_id": tctx.request_id,
        },
    )
    await ctx.hub.publish(
        ctx.conversation_id, "tool.call",
        {"name": tool.name, "input": tctx.input_data, "plan_index": 0, "request_id": tctx.request_id},
        call_seq,
    )

    timeout_s = execution.get("timeout_s", 5)
    if tool.name == "submit_forecast":
        timeout_s = max(float(timeout_s), FORECAST_TOOL_TIMEOUT_S)
    started = time.monotonic()
    try:
        output = await asyncio.wait_for(
            run_internal(
                tool.name,
                tctx.input_data,
                context={"session": session, "user_id": ctx.user_id},
            ),
            timeout=timeout_s,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - started) * 1000)
        err_seq = await append_event(
            session, trace_id=ctx.trace_id, message_id=ctx.message_id, type=TOOL_ERROR,
            payload={"name": tool.name, "error_code": "TIMEOUT", "message": "内部工具执行超时", "retried": 0},
        )
        await ctx.hub.publish(
            ctx.conversation_id, "tool.error",
            {"name": tool.name, "error_code": "TIMEOUT", "message": "内部工具执行超时", "retried": 0},
            err_seq,
        )
        return {
            "ok": False, "output": None,
            "error": {"code": "TIMEOUT", "message": "内部工具执行超时", "retryable": False},
            "duration_ms": duration_ms, "request_id": tctx.request_id,
        }
    except Exception as exc:  # noqa: BLE001
        from app.utils.errors import ValidationError as _VE

        duration_ms = int((time.monotonic() - started) * 1000)
        code = "VALIDATION" if isinstance(exc, _VE) else "INTERNAL"
        err_seq = await append_event(
            session, trace_id=ctx.trace_id, message_id=ctx.message_id, type=TOOL_ERROR,
            payload={"name": tool.name, "error_code": code, "message": str(exc), "retried": 0},
        )
        await ctx.hub.publish(
            ctx.conversation_id, "tool.error",
            {"name": tool.name, "error_code": code, "message": str(exc), "retried": 0},
            err_seq,
        )
        return {
            "ok": False, "output": None,
            "error": {"code": code, "message": str(exc), "retryable": False},
            "duration_ms": duration_ms, "request_id": tctx.request_id,
        }

    result_seq = await append_event(
        session,
        trace_id=ctx.trace_id,
        message_id=ctx.message_id,
        type=TOOL_RESULT,
        payload={"name": tool.name, "output": output, "duration_ms": duration_ms, "status": "ok"},
    )
    # T43：internal 工具全文透传（不截断摘要），SSE tool.result 载荷完整携带 spec
    await ctx.hub.publish(
        ctx.conversation_id, "tool.result",
        {"name": tool.name, "output_summary": output, "duration_ms": duration_ms, "status": "ok"},
        result_seq,
    )
    return {
        "ok": True, "output": output,
        "error": None, "duration_ms": duration_ms, "request_id": tctx.request_id,
    }


def _summarize(output: Any) -> Any:
    """输出摘要（SSE tool.result 只发摘要，完整数据在 message_event payload）。"""
    if isinstance(output, dict):
        if "rows" in output:
            rows = output["rows"]
            return {"rows_count": len(rows) if isinstance(rows, list) else rows}
        if "forecast" in output:
            f = output["forecast"]
            return {"forecast": f if isinstance(f, list) and len(f) <= 5 else (f[:5] if isinstance(f, list) else f)}
    if isinstance(output, str) and len(output) > 2000:
        return output[:2000]
    return output


async def build_messages_for(
    session: AsyncSession,
    conversation_id: str,
    prompt: str,
    user_max_messages: int = 48,
) -> list[dict[str, Any]]:
    """组装上下文（tech_design §3.3 build_messages，T16 供 loop 使用，T17 亦复用）。"""
    from sqlalchemy import select

    from app.models import Message

    rows = (
        await session.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
                Message.status.in_(("sent", "completed", "interrupted")),
            )
            .order_by(Message.created_at.desc())
            .limit(user_max_messages)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    msgs: list[dict[str, Any]] = []
    for m in rows:
        msgs.append({"role": m.role, "content": m.content})
    msgs.append({"role": "user", "content": prompt})
    return msgs


async def run_flow(rctx: RunContext, prompt: str, session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """执行完整 Agent 循环。返回最终状态（engine 调用后由 chat_service 持久化消息）。"""
    ctx = rctx
    final_status = MessageStatus.COMPLETED
    final_text = ""

    async with session_factory() as session:
        try:
            await _emit_agent_state(session, ctx, EngineState.STARTING)

            # 上下文组装（含 T17 user prompt）
            user_max = await get_sys_config(session, "conversation.user_max_messages", 48)
            from app.services.chat_context import build_context

            msgs = await build_context(
                session,
                ctx.conversation_id,
                prompt,
                user_max_messages=int(user_max),
            )
            tools = [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "input_schema": s["input_schema"],
                }
                for s in await _scenario_tools(session, ctx.scenario)
            ]

            provider = await _resolve_provider(session, ctx.scenario)
            model_ref = (ctx.scenario.model_ref or {})
            llm_params = {"model": model_ref.get("model") or provider.default_model}
            if ctx.oa:
                llm_params["oa"] = ctx.oa
            if ctx.oauth_access_token:
                # T08's gateway adapter maps this provider option to its
                # request-scoped `inputs.new_token`; it is never persisted.
                llm_params["access_token"] = ctx.oauth_access_token

            checkpoint_counter = 0
            llm_attempt = 0
            fallbacked = False
            degrade_reason = ""
            done_message_seq = 0
            final_usage: Optional[dict] = None  # T38：done 载荷可选的 usage
            result_envelope: dict[str, Any] | None = None
            #: 工具连续失败熔断（同一轮内所有工具全失败达阈值 → 终止，防死循环）
            consecutive_tool_failures = 0
            MAX_CONSECUTIVE_TOOL_FAILURES = 2
            #: Agent 总轮数上限（防止模型持续重复工具调用导致死循环；§3.4 收敛保障）
            MAX_AGENT_ROUNDS = 10

            while True:
                if checkpoint_counter >= MAX_AGENT_ROUNDS and checkpoint_counter > 0:
                    final_status = MessageStatus.COMPLETED
                    final_text = "已达到本轮执行轮数上限，请重试或换一种问法。"
                    done_message_seq = await append_event(
                        session,
                        trace_id=ctx.trace_id,
                        message_id=ctx.message_id,
                        type=DONE,
                        payload={"final_text": final_text, "status": "completed"},
                    )
                    break
                if ctx.flow.cancelled:
                    final_status = MessageStatus.INTERRUPTED
                    seq = await append_event(
                        session,
                        trace_id=ctx.trace_id,
                        message_id=ctx.message_id,
                        type=AGENT_PROCESS,
                        payload={"state": "interrupted", "detail": "用户停止生成"},
                    )
                    await ctx.hub.publish(
                        ctx.conversation_id, "agent.process",
                        {"state": "interrupted", "detail": "用户停止生成"}, seq,
                    )
                    break

                await _emit_agent_state(session, ctx, EngineState.PLANNING)
                stream_ok = False
                stop_reason = "stop"
                tool_calls: list[Any] = []
                text_buffer: list[str] = []
                error_code = ""
                usage: Optional[dict] = None  # T38：本轮 LLM 末 chunk usage

                try:
                    async for evt in provider.chat(msgs, tools, llm_params):
                        if evt.type == "content_delta":
                            text_buffer.append(evt.text)
                            await _emit_content_delta(ctx, evt.text)
                        elif evt.type == "tool_call.batch":
                            tool_calls = evt.calls
                        elif evt.type == "done_reason":
                            stop_reason = evt.stop_reason
                            if getattr(evt, "usage", None) is not None:
                                usage = evt.usage
                        elif evt.type == "error":
                            error_code = evt.code
                    stream_ok = True
                except Exception:  # noqa: BLE001
                    logger.exception("llm stream error")
                    error_code = "UPSTREAM"

                # 重试/降级（LLM 错误）
                if not stream_ok or error_code:
                    if llm_error_retryable(error_code) and llm_attempt < MAX_LLM_RETRIES:
                        llm_attempt += 1
                        detail = f"LLM 调用失败 {error_code}，重试 {llm_attempt}/{MAX_LLM_RETRIES}"
                        await _emit_agent_state(session, ctx, EngineState.RETRYING, detail)
                        await asyncio.sleep(backoff_delay(llm_attempt))
                        continue
                    # 降级到 fallback provider（仅一次）
                    if not fallbacked and (ctx.scenario.model_ref or {}).get("fallback"):  # noqa: SIM102
                        pass  # fallback 由 provider 层决定——见 _resolve_provider
                    if not fallbacked:
                        fallbacked = True
                        degrade_reason = "LLM 持续失败，降级处理"
                        await _emit_agent_state(session, ctx, EngineState.DEGRADING, degrade_reason)
                        # 未能恢复 → 本轮失败
                        final_status = MessageStatus.FAILED
                        final_text = "抱歉，模型服务暂时不可用，请稍后再试。"
                        break

                # SavePoint：每轮 LLM 前 checkpoint
                checkpoint_counter += 1
                await save_checkpoint(
                    session,
                    conversation_id=ctx.conversation_id,
                    message_id=ctx.message_id,
                    trace_id=ctx.trace_id,
                    messages_snapshot=msgs,
                    engine_cursor=checkpoint_counter,
                    scenario_id=str(ctx.scenario.id),
                    provider_id=str(getattr(provider, "provider_id", None) or ""),
                )
                await session.commit()  # checkpoint 落库（SafePoint）

                # tool_use → 执行工具
                if stop_reason == "tool_use" and tool_calls:
                    await _emit_agent_state(session, ctx, EngineState.EXECUTING)
                    results = await _execute_tools_parallel(session, ctx, tool_calls, tools)
                    for tool_result in results:
                        candidate = tool_result.get("output") if isinstance(tool_result, dict) else None
                        if isinstance(candidate, dict) and candidate.get("response_type") not in (None, "need_input"):
                            result_envelope = candidate
                    # 回灌
                    msgs.append({"role": "assistant", "content": "".join(text_buffer), "tool_calls": _tool_call_payloads(tool_calls)})
                    for i, (tc, res) in enumerate(zip(tool_calls, results, strict=False)):
                        msgs.append(_make_tool_message(tc.name, tc.id, res))
                    await session.commit()  # 工具结果落库

                    # 工具连续失败熔断（§3.4：失败不中断会话，但需收敛防死循环）
                    failed = [r for r in results if not r.get("ok", False)]
                    if failed:
                        consecutive_tool_failures += 1
                    else:
                        consecutive_tool_failures = 0
                    if (
                        consecutive_tool_failures >= MAX_CONSECUTIVE_TOOL_FAILURES
                        and len(results) == len(tool_calls)
                    ):
                        final_text = "抱歉，工具执行持续失败，无法完成本次请求。请稍后重试或检查数据源状态。"
                        final_status = MessageStatus.COMPLETED
                        done_message_seq = await append_event(
                            session,
                            trace_id=ctx.trace_id,
                            message_id=ctx.message_id,
                            type=DONE,
                            payload={"final_text": final_text, "status": "completed"},
                        )
                        break
                    # SafePoint：回灌后检查中断
                    if ctx.flow.cancelled:
                        final_status = MessageStatus.INTERRUPTED
                        break
                    continue

                # 正常结束
                final_text = "".join(text_buffer) if text_buffer else (
                    tool_calls and "已获取工具结果，请提出下一步问题。" or ""
                )
                final_usage = usage
                done_message_seq = await append_event(
                    session,
                    trace_id=ctx.trace_id,
                    message_id=ctx.message_id,
                    type=DONE,
                    payload={"final_text": final_text, "status": "completed", **({"usage": usage} if usage else {})},
                )
                break

            # 持久化助手消息终态
            msg = await session.get(Message, ctx.message_id)
            if msg is not None:
                msg.content = final_text
                msg.status = final_status.value
                if result_envelope is not None:
                    msg.result_envelope = result_envelope
            if final_status == MessageStatus.COMPLETED:
                from app.services.memory import update_memory

                await update_memory(
                    session,
                    ctx.conversation_id,
                    capability=(result_envelope or {}).get("response_type") if result_envelope else None,
                    commit=False,
                )
            await session.commit()
            await ctx.hub.publish(
                ctx.conversation_id, "done",
                {"message_id": ctx.message_id, "final_text": final_text, "status": final_status.value,
                 **({"usage": final_usage} if final_usage else {})},
                done_message_seq,
            )

            # T32：done 后追加轻量 LLM 调用生成 follow-up 建议（不落库，仅 SSE；失败静默降级）
            if final_status == MessageStatus.COMPLETED:
                await _publish_follow_ups(ctx, final_text, provider, llm_params)
        except Exception:
            logger.exception("run_flow failed conversation=%s", ctx.conversation_id)
            async with session_factory() as s2:
                msg = await s2.get(Message, ctx.message_id)
                if msg is not None:
                    msg.status = MessageStatus.FAILED.value
                await s2.commit()
            final_status = MessageStatus.FAILED
            final_text = "执行失败，请重试"
            try:
                seq = await append_event(
                    session,
                    trace_id=ctx.trace_id,
                    message_id=ctx.message_id,
                    type=AGENT_PROCESS,
                    payload={"state": "done", "detail": "flow failed"},
                )
                await ctx.hub.publish(ctx.conversation_id, "error", {"code": "500_INTERNAL", "message": "执行失败"}, seq)
            except Exception:  # noqa: S110, BLE001
                pass

    return {"status": final_status.value, "final_text": final_text}


# ------------------------------------------------------------------
# T32：follow-up 建议生成（done 后一次轻量非流式调用，不落库）
# ------------------------------------------------------------------
FOLLOW_UP_TIMEOUT_S = 5
_FOLLOW_UP_SYSTEM = (
    "你是一名销售数据分析助手。基于助手刚刚给出的回答，生成 3 条用户最可能"
    "追问的短问题（操作或提问，每条不超过 24 字）。"
    '严格输出 JSON 数组，形如 [{"id":"1","text":"…"},{"id":"2","text":"…"},{"id":"3","text":"…"}]，'
    "不要输出任何其他文字。"
)


async def _publish_follow_ups(ctx: RunContext, final_text: str, provider: Any, llm_params: dict) -> None:
    """生成 3 条 follow-up 建议并经 SSE 推送；任何失败（超时/非 JSON/异常）静默跳过。"""
    try:
        raw = await asyncio.wait_for(
            provider.complete(
                [
                    {"role": "system", "content": _FOLLOW_UP_SYSTEM},
                    {"role": "assistant", "content": final_text or "（助手未输出正文）"},
                ],
                llm_params,
            ),
            timeout=FOLLOW_UP_TIMEOUT_S,
        )
    except Exception:  # noqa: BLE001
        logger.warning("follow-up 生成失败，跳过建议（不阻断主流程）", exc_info=True)
        return
    try:
        items = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.warning("follow-up 响应非 JSON，跳过")
        return
    if not isinstance(items, list):
        return
    suggestions = []
    for idx, item in enumerate(items[:3], start=1):
        if isinstance(item, dict) and item.get("text"):
            text = str(item["text"]).strip()
            if text:
                suggestions.append({"id": str(item.get("id", str(idx))), "text": text})
    if suggestions:
        await ctx.hub.publish(
            ctx.conversation_id,
            EVT_FOLLOW_UP,
            SsePayload.follow_up(ctx.message_id, suggestions),
        )


async def _scenario_tools(session: AsyncSession, scenario: Any) -> list[dict[str, Any]]:
    from app.tools.scenario import enabled_tools

    return await enabled_tools(session, scenario)


async def _resolve_provider(session: AsyncSession, scenario: Any) -> Any:
    from app.llm.mock_provider import MockProvider  # noqa: F401
    from app.llm.service import get_default_provider
    from app.utils.security import decrypt_secret

    provider = await get_default_provider(session)
    if provider is None:
        # 无配置 → 用 mock provider（外部依赖未真连时降级路线）
        from app.llm.mock_provider import MockProvider

        return MockProvider("mock", "default", "")

    api_key = decrypt_secret(provider.api_key_encrypted)
    from app.llm.providers import get_provider as build_provider

    return build_provider(provider, api_key)


def _tool_call_payloads(tool_calls: list[Any]) -> list[dict[str, Any]]:
    out = []
    for tc in tool_calls:
        out.append({"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": __import__("json").dumps(tc.arguments)}})
    return out


async def _execute_tools_parallel(
    session: AsyncSession,
    ctx: RunContext,
    tool_calls: list[Any],
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """并行执行工具调用（最大并发读 system_config.sandbox.max_concurrent）。"""
    tool_by_name = {t["name"]: t for t in tools}
    # 从 DB 载入 Tool 实体
    from app.models import Tool

    max_concurrent = 3
    try:
        from app.config_service import get_sys_config

        max_concurrent = int(await get_sys_config(session, "sandbox.max_concurrent", 3))
    except Exception:  # noqa: BLE001
        pass
    sem = asyncio.Semaphore(max_concurrent)
    tasks: list[asyncio.Task] = []

    async def _guarded(tctx: ToolExecutionContext) -> dict[str, Any]:
        async with sem:
            return await _execute_one_tool(session, ctx, tctx, max_concurrent)

    for tc in tool_calls:
        tool_dict = tool_by_name.get(tc.name)
        if tool_dict is None:
            # 非法工具调用 → tool_error(VALIDATION)
            seq = await append_event(
                session,
                trace_id=ctx.trace_id,
                message_id=ctx.message_id,
                type=TOOL_ERROR,
                payload={"name": tc.name, "error_code": "VALIDATION", "message": "模型调用了未注册工具", "retried": 0},
            )
            await ctx.hub.publish(ctx.conversation_id, "tool.error", {"name": tc.name, "error_code": "VALIDATION", "message": "未注册工具", "retried": 0}, seq)
            continue
        tool = (
            await session.execute(
                __import__("sqlalchemy").select(Tool).where(Tool.name == tc.name)
            )
        ).scalars().first()
        tctx = ToolExecutionContext(call_id=tc.id, tool=tool, input_data=tc.arguments)
        tasks.append(_guarded(tctx))

    if not tasks:
        return []
    results = await asyncio.gather(*tasks)
    return list(results)
