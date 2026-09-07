"""真实 HTTP 聊天场景验收脚本。

脚本不 mock LLM，调用工作台 ``POST /api/chat/stream``，再用返回的
``session_id/message_id`` 回查原生消息 trace。它输出可观察的状态、工具规划、
工具入参/结果、最终 envelope 和持久化结果；不会尝试输出模型隐藏思维内容。

用法示例（从 backend 目录执行）：
    CHAT_ACCESS_TOKEN=... uv run python tests/chat_request.py --case history --strict
    CHAT_TEST_EMAIL=... CHAT_TEST_PASSWORD=... \
        uv run python tests/chat_request.py --case history --case forecast --strict
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CATEGORY = "冰箱"
DEFAULT_TIMEOUT_S = 360.0
DEFAULT_CASE_NAMES = (
    "history",
    "forecast",
    "attribution",
    "optimization",
    "optimization_target",
    "simulation",
    "missing",
)
CASE_NAMES = (*DEFAULT_CASE_NAMES,)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|authorization|password|secret|api[_-]?key|credential|cookie)", re.IGNORECASE
)


class ChatRequestError(RuntimeError):
    """脚本自身的协议/环境错误，不混淆为业务回答。"""


@dataclass(frozen=True)
class CaseSpec:
    name: str
    prompt: str
    expected_types: tuple[str, ...] = ()
    required_tool_order: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    min_tool_counts: tuple[tuple[str, int], ...] = ()
    reply_terms: tuple[str, ...] = ()
    expected_target_qty: float | None = None
    expected_target_revenue: float | None = None
    requires_default_target: bool = False
    note: str = ""


@dataclass
class AuthContext:
    headers: dict[str, str]
    gateway_body: dict[str, str] = field(default_factory=dict)
    secret_values: tuple[str, ...] = ()


@dataclass
class StreamCapture:
    events: list[str] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    deltas: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    done: dict[str, Any] | None = None
    elapsed_ms: int = 0
    first_event_ms: int | None = None


@dataclass
class CaseRun:
    spec: CaseSpec
    prompt: str
    capture: StreamCapture | None = None
    trace: dict[str, Any] | None = None
    session_detail: dict[str, Any] | None = None
    session_id: str | None = None
    message_id: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = False


def _next_month() -> str:
    now = datetime.now()
    year = now.year + (1 if now.month == 12 else 0)
    month = 1 if now.month == 12 else now.month + 1
    return f"{year:04d}-{month:02d}"


def _validate_month(value: str) -> str:
    if not _MONTH_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("预测月份必须为 YYYY-MM，例如 2026-10")
    return value


def build_cases(category: str, forecast_month: str) -> dict[str, CaseSpec]:
    """构造固定问题集；工具顺序是观测断言，不是隐藏 CoT 断言。"""
    return {
        "history": CaseSpec(
            name="history",
            prompt=f"查询{category}近半年销售情况",
            expected_types=("history",),
            required_tool_order=("get_history",),
            forbidden_tools=("submit_forecast", "get_forecast_result", "get_attribution"),
            note="历史/实际问题只能走 get_history。",
        ),
        "forecast": CaseSpec(
            name="forecast",
            prompt=f"预测{category}以 {forecast_month} 为基准未来3个月销量",
            expected_types=("forecast",),
            required_tool_order=("submit_forecast", "get_forecast_result"),
            forbidden_tools=("get_attribution",),
            note="预测必须先提交任务，再按返回版本读取结构化预测。",
        ),
        "attribution": CaseSpec(
            name="attribution",
            prompt=f"预测{category}以 {forecast_month} 为基准的 TOP5 型号销售趋势并分析",
            expected_types=("forecast", "attribution"),
            required_tool_order=("submit_forecast", "get_forecast_result", "get_attribution"),
            min_tool_counts=(("get_attribution", 5),),
            note="归因型号应来自 get_forecast_result.top_skus，且沿用同一预测版本。",
        ),
        "optimization": CaseSpec(
            name="optimization",
            prompt=f"帮我制定{category}下月销售计划",
            expected_types=("optimization",),
            required_tool_order=("submit_forecast", "get_forecast_result", "get_whatif_strategies", "optimize"),
            forbidden_tools=("simulate",),
            min_tool_counts=(("get_whatif_strategies", 1),),
            requires_default_target=True,
            note="计划先建立预测 baseline，再读有限策略目录、比较目标差距并调用 optimize；未给目标使用工作台默认目标。",
        ),
        "optimization_target": CaseSpec(
            name="optimization_target",
            prompt=f"帮我制定{category}下月销售计划，目标销量 4 万台，目标销售额 500 万元",
            expected_types=("optimization",),
            required_tool_order=("submit_forecast", "get_forecast_result", "get_whatif_strategies", "optimize"),
            forbidden_tools=("simulate",),
            min_tool_counts=(("get_whatif_strategies", 1),),
            expected_target_qty=40_000,
            expected_target_revenue=5_000_000,
            note="显式目标必须进入 optimize 的 target_qty/target_revenue，不能被默认目标覆盖。",
        ),
        "simulation": CaseSpec(
            name="simulation",
            prompt=f"如果我把{category}主销型号降价8%，之后会怎么样",
            expected_types=("simulation",),
            required_tool_order=("get_whatif_strategies", "simulate"),
            note="What-if 策略先读取目录，不能由模型臆造 strategy_id。",
        ),
        "missing": CaseSpec(
            name="missing",
            prompt="预测未来3个月销量",
            expected_types=("report",),
            reply_terms=("品类", "类别"),
            note="缺少品类时应询问输入或返回 need_input(category)，不能猜测品类。",
        ),
    }


def _redact(value: Any, secret_values: Iterable[str] = ()) -> Any:
    """递归脱敏，避免脚本输出 JWT、OAuth token 或凭据字段。"""
    secrets = tuple(item for item in secret_values if item and len(item) >= 4)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)):
                result[str(key)] = "***REDACTED***"
            else:
                result[str(key)] = _redact(item, secrets)
        return result
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "***REDACTED***")
        return result
    return value


def _compact(value: Any, secret_values: Iterable[str] = (), limit: int = 1800) -> str:
    safe = _redact(value, secret_values)
    if isinstance(safe, str):
        text = safe
    else:
        text = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > limit:
        return f"{text[:limit]}…[已截断，共 {len(text)} 字符]"
    return text


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _response_error(response: httpx.Response, secret_values: Iterable[str] = ()) -> str:
    payload = _response_payload(response)
    return f"HTTP {response.status_code}: {_compact(payload, secret_values, limit=800)}"


def _json_object(response: httpx.Response, endpoint: str, secret_values: Iterable[str] = ()) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise ChatRequestError(f"{endpoint} 请求失败，{_response_error(response, secret_values)}")
    payload = _response_payload(response)
    if not isinstance(payload, dict):
        raise ChatRequestError(f"{endpoint} 返回体不是 JSON 对象")
    return payload


def _extract_data(payload: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """读取原生统一响应壳 data；façade/health 裸 JSON 则直接返回。"""
    if "data" in payload and "code" in payload:
        if str(payload.get("code")) != "0":
            raise ChatRequestError(f"{endpoint} 业务失败：{payload.get('message', '未知错误')}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ChatRequestError(f"{endpoint} data 不是 JSON 对象")
        return data
    return payload


def authenticate(client: httpx.Client, args: argparse.Namespace) -> AuthContext:
    """优先使用 JWT；没有 JWT 时使用 email/password 或 OA 登录。"""
    access_token = (args.access_token or os.getenv("CHAT_ACCESS_TOKEN") or "").strip()
    if access_token:
        raw_token = access_token[7:].strip() if access_token.lower().startswith("bearer ") else access_token
        return AuthContext(
            headers={"Authorization": f"Bearer {raw_token}"},
            secret_values=(raw_token,),
        )

    oa = (args.oa or os.getenv("CHAT_TEST_OA") or "").strip()
    if oa:
        response = client.post("/api/auth/login", json={"oa": oa})
        payload = _json_object(response, "/api/auth/login")
        data = _extract_data(payload, "/api/auth/login")
        local_token = str(data.get("access_token") or "").strip()
        oauth_token = str(data.get("oauth_access_token") or "").strip()
        if not local_token:
            raise ChatRequestError("OA 登录成功响应缺少 access_token")
        gateway_body = {"oa": oa}
        if oauth_token:
            gateway_body["access_token"] = oauth_token
        return AuthContext(
            headers={"Authorization": f"Bearer {local_token}"},
            gateway_body=gateway_body,
            secret_values=tuple(item for item in (local_token, oauth_token) if item),
        )

    email = (args.email or os.getenv("CHAT_TEST_EMAIL") or "chat-request@corp.com").strip()
    password = args.password or os.getenv("CHAT_TEST_PASSWORD") or ""
    if not password:
        raise ChatRequestError(
            "未找到认证信息：请设置 CHAT_ACCESS_TOKEN，或同时设置 CHAT_TEST_EMAIL/CHAT_TEST_PASSWORD。"
        )

    if args.register:
        register_response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "nickname": "chat-request-test"},
        )
        if register_response.status_code not in (200, 201, 409):
            raise ChatRequestError(f"注册测试账号失败，{_response_error(register_response, (password,))}")

    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    payload = _json_object(response, "/api/v1/auth/login", (password,))
    data = _extract_data(payload, "/api/v1/auth/login")
    local_token = str(data.get("access_token") or "").strip()
    if not local_token:
        raise ChatRequestError("登录成功响应缺少 access_token")
    return AuthContext(
        headers={"Authorization": f"Bearer {local_token}"},
        secret_values=(local_token, password),
    )


def read_sse(response: httpx.Response) -> Iterator[tuple[str, dict[str, Any]]]:
    """解析 façade 的 event/data SSE 帧，兼容 CRLF 和分块传输。"""
    event_name = "message"
    data_lines: list[str] = []

    def emit() -> tuple[str, dict[str, Any]] | None:
        if not data_lines:
            return None
        raw = "\n".join(data_lines).strip()
        current_event = event_name
        if raw == "[DONE]":
            return current_event, {"_done_marker": True}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChatRequestError(f"SSE data 不是合法 JSON：{raw[:180]}") from exc
        if not isinstance(payload, dict):
            raise ChatRequestError("SSE data 必须是 JSON 对象")
        return current_event, payload

    for line in response.iter_lines():
        if line == "":
            item = emit()
            event_name = "message"
            data_lines = []
            if item is not None:
                if item[1].get("_done_marker"):
                    return
                yield item
            continue
        if line.startswith(":") or line.startswith("id:"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    item = emit()
    if item is not None and not item[1].get("_done_marker"):
        yield item


def stream_case(
    client: httpx.Client,
    auth: AuthContext,
    spec: CaseSpec,
    *,
    session_id: str | None,
    timeout_s: float,
) -> StreamCapture:
    payload: dict[str, Any] = {
        "message": spec.prompt,
        "session_id": session_id,
        "params": {},
        **auth.gateway_body,
    }
    headers = {
        **auth.headers,
        "Idempotency-Key": f"chat-request-{spec.name}-{uuid.uuid4().hex}",
    }
    capture = StreamCapture()
    started = time.monotonic()
    with client.stream("POST", "/api/chat/stream", headers=headers, json=payload) as response:
        if response.status_code < 200 or response.status_code >= 300:
            raise ChatRequestError(f"/api/chat/stream 请求失败，{_response_error(response, auth.secret_values)}")
        for event, data in read_sse(response):
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms > int(timeout_s * 1000):
                raise ChatRequestError(f"/api/chat/stream 超过 {timeout_s:.0f}s 超时上限")
            if capture.first_event_ms is None:
                capture.first_event_ms = elapsed_ms
            capture.events.append(event)
            if event == "status":
                capture.statuses.append(data)
            elif event == "delta":
                capture.deltas.append(str(data.get("text") or ""))
            elif event == "result":
                capture.result = data
            elif event == "done":
                capture.done = data
    capture.elapsed_ms = int((time.monotonic() - started) * 1000)
    return capture


def fetch_trace_and_session(
    client: httpx.Client,
    auth: AuthContext,
    session_id: str,
    message_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    trace_response = client.get(
        f"/api/v1/chat/conversations/{session_id}/messages/{message_id}/trace",
        headers=auth.headers,
    )
    trace_payload = _json_object(trace_response, "trace", auth.secret_values)
    trace = _extract_data(trace_payload, "trace")

    session_response = client.get(f"/api/sessions/{session_id}", headers=auth.headers)
    session_detail = _json_object(session_response, "/api/sessions/{session_id}", auth.secret_values)
    return trace, session_detail


def _tool_calls(trace: dict[str, Any]) -> list[str]:
    return [
        str(event.get("payload", {}).get("name") or "")
        for event in trace.get("events", [])
        if event.get("type") == "tool_call" and event.get("payload", {}).get("name")
    ]


def _field(value: Any, *names: str) -> Any:
    if not isinstance(value, dict):
        return None
    for name in names:
        if value.get(name) not in (None, ""):
            return value[name]
    for nested_name in ("meta", "envelope"):
        nested = value.get(nested_name)
        if isinstance(nested, dict):
            for name in names:
                if nested.get(name) not in (None, ""):
                    return nested[name]
    return None


def _tool_records(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """按工具名/出现顺序配对 trace 中的 call 与 result。"""
    pending_inputs: dict[str, list[Any]] = {}
    records: list[dict[str, Any]] = []
    for event in trace.get("events", []):
        payload = event.get("payload", {})
        name = str(payload.get("name") or "")
        if event.get("type") == "tool_call" and name:
            pending_inputs.setdefault(name, []).append(payload.get("input", {}))
        elif event.get("type") in {"tool_result", "tool_error"} and name:
            inputs = pending_inputs.get(name, [])
            records.append(
                {
                    "name": name,
                    "input": inputs.pop(0) if inputs else {},
                    "output": payload.get("output"),
                    "status": payload.get("status") or ("error" if event.get("type") == "tool_error" else ""),
                    "error_code": payload.get("error_code"),
                }
            )
    return records


def _semantic_issues(spec: CaseSpec, trace: dict[str, Any]) -> list[str]:
    """对版本、SKU、策略目录做轻量证据一致性检查。"""
    records = _tool_records(trace)
    outputs = {
        name: [record for record in records if record["name"] == name and isinstance(record.get("output"), dict)]
        for name in {record["name"] for record in records}
    }
    issues: list[str] = []
    if spec.name in {"forecast", "attribution"}:
        submitted = outputs.get("submit_forecast", [])
        forecast_results = outputs.get("get_forecast_result", [])
        submit_version = _field(submitted[-1].get("output"), "system_forecast_number", "forecast_version", "version") if submitted else None
        result_version = _field(forecast_results[-1].get("output"), "system_forecast_number", "forecast_version", "version") if forecast_results else None
        result_input_version = _field(forecast_results[-1].get("input"), "system_forecast_number", "forecast_version", "version") if forecast_results else None
        if submit_version and result_version and str(submit_version) != str(result_version):
            issues.append(f"submit_forecast 版本 {submit_version} 与 get_forecast_result 版本 {result_version} 不一致")
        if submit_version and result_input_version and str(submit_version) != str(result_input_version):
            issues.append(f"get_forecast_result 入参版本 {result_input_version} 未沿用 {submit_version}")

        if spec.name == "attribution" and forecast_results:
            forecast_output = forecast_results[-1].get("output")
            top_skus = {
                str(item.get("sku"))
                for item in (forecast_output or {}).get("top_skus", [])
                if isinstance(item, dict) and item.get("sku") not in (None, "")
            }
            for record in outputs.get("get_attribution", []):
                output = record.get("output") or {}
                sku = _field(output, "sku") or _field(record.get("input"), "sku")
                version = _field(output, "system_forecast_number", "forecast_version", "version")
                if top_skus and sku and str(sku) not in top_skus:
                    issues.append(f"归因 SKU {sku} 不在 forecast.top_skus 中")
                if submit_version and version and str(version) != str(submit_version):
                    issues.append(f"归因版本 {version} 未沿用预测版本 {submit_version}")

    if spec.name == "simulation":
        catalog_items = [
            item
            for record in outputs.get("get_whatif_strategies", [])
            for item in (record.get("output") or {}).get("strategies", [])
            if isinstance(item, dict)
        ]
        ids = {str(item.get("id")) for item in catalog_items if item.get("id") not in (None, "")}
        names = {str(item.get("name")) for item in catalog_items if item.get("name") not in (None, "")}
        for record in outputs.get("simulate", []):
            requested = _field(record.get("input"), "strategy_id", "strategy_name", "strategy")
            if requested and catalog_items and str(requested) not in ids and str(requested) not in names:
                issues.append(f"simulate 策略 {requested} 不在 get_whatif_strategies 返回目录中")

    if spec.name in {"optimization", "optimization_target"}:
        catalog_items = [
            item
            for record in outputs.get("get_whatif_strategies", [])
            for item in (record.get("output") or {}).get("strategies", [])
            if isinstance(item, dict)
        ]
        catalog_ids = {str(item.get("id")) for item in catalog_items if item.get("id") not in (None, "")}
        catalog_names = {str(item.get("name")) for item in catalog_items if item.get("name") not in (None, "")}
        optimize_records = outputs.get("optimize", [])
        if optimize_records:
            optimize_output = optimize_records[-1].get("output") or {}
            optimize_input = optimize_records[-1].get("input") or {}
            meta = optimize_output.get("meta") if isinstance(optimize_output.get("meta"), dict) else {}
            goal = meta.get("goal_vs_baseline") if isinstance(meta.get("goal_vs_baseline"), dict) else {}
            qty_goal = goal.get("qty") if isinstance(goal.get("qty"), dict) else {}
            if qty_goal.get("gap") is None:
                issues.append("optimize 没有返回 baseline 与目标销量的差距")
            result = optimize_output.get("envelope") if isinstance(optimize_output.get("envelope"), dict) else {}
            result = result.get("result") if isinstance(result.get("result"), dict) else {}
            for row in result.get("rows", []) if isinstance(result.get("rows"), list) else []:
                if not isinstance(row, dict) or not catalog_items:
                    continue
                strategy_id = row.get("strategy_id")
                strategy_name = row.get("strategy_name")
                if (
                    strategy_id not in (None, "")
                    and str(strategy_id) not in catalog_ids
                    and str(strategy_id) not in catalog_names
                ) or (
                    strategy_name not in (None, "")
                    and str(strategy_name) not in catalog_ids
                    and str(strategy_name) not in catalog_names
                ):
                    issues.append(
                        f"optimize 策略 {strategy_id or strategy_name} 不在 get_whatif_strategies 返回目录中"
                    )
                    break
            if spec.expected_target_qty is not None:
                actual_input = optimize_input.get("target_qty")
                if actual_input not in (None, "") and abs(float(actual_input) - spec.expected_target_qty) > 0.01:
                    issues.append(
                        f"optimize 实际入参 target_qty={actual_input!r}，期望 {spec.expected_target_qty:g}"
                    )
            if spec.expected_target_revenue is not None:
                actual_input = optimize_input.get("target_revenue")
                if actual_input not in (None, "") and abs(float(actual_input) - spec.expected_target_revenue) > 0.01:
                    issues.append(
                        f"optimize 实际入参 target_revenue={actual_input!r}，期望 {spec.expected_target_revenue:g}"
                    )
        else:
            issues.append("trace 没有 optimize 成功结果，无法核对目标差距")
    return issues


def _contains_in_order(actual: list[str], expected: tuple[str, ...]) -> bool:
    if not expected:
        return True
    position = 0
    for name in actual:
        if name == expected[position]:
            position += 1
            if position == len(expected):
                return True
    return False


def _event_chain(events: Iterable[str]) -> str:
    result: list[str] = []
    for event in events:
        if result and result[-1].startswith(f"{event}×"):
            name, count = result[-1].split("×", 1)
            result[-1] = f"{name}×{int(count) + 1}"
        elif result and result[-1] == event:
            result[-1] = f"{event}×2"
        else:
            result.append(event)
    return " → ".join(result) if result else "（无事件）"


def _envelope_summary(envelope: Any, secret_values: Iterable[str]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {"value": _redact(envelope, secret_values)}
    meta = envelope.get("meta") if isinstance(envelope.get("meta"), dict) else {}
    chart = envelope.get("chart") if isinstance(envelope.get("chart"), dict) else {}
    cards = chart.get("cards") if isinstance(chart.get("cards"), list) else []
    table = envelope.get("table") if isinstance(envelope.get("table"), dict) else {}
    return {
        "response_type": envelope.get("response_type"),
        "intent": envelope.get("intent"),
        "update_workspace": envelope.get("update_workspace"),
        "meta": _redact(meta, secret_values),
        "chart_cards": [item.get("type") for item in cards if isinstance(item, dict)],
        "chart_card_titles": [item.get("title") for item in cards if isinstance(item, dict)],
        "table_rows": len(table.get("rows", [])) if isinstance(table.get("rows"), list) else None,
        "process_steps": _redact(envelope.get("process_steps", []), secret_values),
    }


def validate_run(
    run: CaseRun,
    *,
    strict: bool,
    secret_values: Iterable[str],
) -> None:
    capture = run.capture
    result = capture.result if capture else None
    done = capture.done if capture else None
    trace = run.trace or {}
    expected_errors: list[str] = []

    if capture is None:
        run.errors.append("没有收到 SSE")
        return
    if "result" not in capture.events:
        run.errors.append("SSE 缺少 result 事件")
    if "done" not in capture.events:
        run.errors.append("SSE 缺少 done 事件")
    if "result" in capture.events and "done" in capture.events:
        if capture.events.index("result") > capture.events.index("done"):
            run.errors.append("SSE 顺序错误：done 出现在 result 之前")
    if not isinstance(result, dict):
        run.errors.append("result 事件载荷不是 JSON 对象")
    if not isinstance(done, dict):
        run.errors.append("done 事件载荷不是 JSON 对象")
    if isinstance(done, dict) and done.get("ok") is not True:
        run.errors.append(f"Agent 未成功完成：ok={done.get('ok')}")

    if isinstance(result, dict):
        run.session_id = str(result.get("session_id") or "") or None
        run.message_id = str(result.get("message_id") or "") or None
        if not run.session_id or not run.message_id:
            run.errors.append("result 缺少 session_id 或 message_id")
        if not isinstance(result.get("envelope"), dict):
            run.errors.append("result 缺少 envelope 对象")

    if run.message_id and trace.get("message_id") and str(trace["message_id"]) != run.message_id:
        run.errors.append("result.message_id 与 trace.message_id 不一致")
    seqs = [event.get("seq") for event in trace.get("events", []) if isinstance(event.get("seq"), int)]
    # Parallel tool calls can reserve the same observable sequence boundary;
    # the event list must still be ordered, but equal adjacent seq values are
    # valid for one parallel batch.
    if seqs and seqs != sorted(seqs):
        run.errors.append("trace seq 不是非递减顺序")
    if run.session_detail is not None and run.message_id:
        messages = run.session_detail.get("messages", [])
        assistant = next((item for item in messages if item.get("id") == run.message_id), None)
        if assistant is None:
            run.errors.append("/api/sessions 未找到 result 对应的 assistant 消息")
        elif isinstance(result, dict) and assistant.get("result_envelope") != result.get("envelope"):
            run.errors.append("持久化 result_envelope 与 SSE result.envelope 不一致")

    actual_type = ((result or {}).get("envelope") or {}).get("response_type") if isinstance(result, dict) else None
    calls = _tool_calls(trace)
    if run.spec.expected_types and actual_type not in run.spec.expected_types:
        expected_errors.append(f"response_type={actual_type!r}，期望 {run.spec.expected_types}")
    if run.spec.required_tool_order and not _contains_in_order(calls, run.spec.required_tool_order):
        expected_errors.append(f"工具顺序 {calls!r} 未包含 {run.spec.required_tool_order!r}")
    for tool_name in run.spec.forbidden_tools:
        if tool_name in calls:
            expected_errors.append(f"历史问题不应调用 {tool_name}")
    counts = {name: calls.count(name) for name, _minimum in run.spec.min_tool_counts}
    for tool_name, minimum in run.spec.min_tool_counts:
        if counts.get(tool_name, 0) < minimum:
            expected_errors.append(f"工具 {tool_name} 调用 {counts.get(tool_name, 0)} 次，至少需要 {minimum} 次")
    if run.spec.reply_terms:
        reply = str((result or {}).get("reply") or "") if isinstance(result, dict) else ""
        if not any(term in reply for term in run.spec.reply_terms):
            expected_errors.append(f"缺少输入提示关键词之一：{run.spec.reply_terms}")
    if isinstance(result, dict) and isinstance(result.get("envelope"), dict):
        envelope = result["envelope"]
        chart = envelope.get("chart") if isinstance(envelope.get("chart"), dict) else {}
        cards = chart.get("cards") if isinstance(chart.get("cards"), list) else []
        line = next((card for card in cards if isinstance(card, dict) and card.get("type") == "line_band"), {})
        line_data = line.get("data") if isinstance(line, dict) and isinstance(line.get("data"), dict) else {}
        top_skus = line_data.get("top_skus") if isinstance(line_data, dict) else []
        if run.spec.name == "forecast" and top_skus:
            expected_errors.append("普通预测 envelope 不应渲染 TOP5；缺少真实归因证据")
        if run.spec.name == "attribution":
            if not top_skus:
                expected_errors.append("TOP5 归因场景没有可渲染的 top_skus")
            waterfall_cards = [
                card for card in cards if isinstance(card, dict) and card.get("type") == "waterfall"
            ]
            if len(waterfall_cards) < 5:
                expected_errors.append(
                    f"TOP5 归因场景只渲染了 {len(waterfall_cards)} 张 waterfall，至少需要 5 张型号归因卡"
                )
        if run.spec.name in {"optimization", "optimization_target"}:
            meta = envelope.get("meta") if isinstance(envelope.get("meta"), dict) else {}
            if run.spec.requires_default_target:
                assumptions = meta.get("assumptions") if isinstance(meta.get("assumptions"), list) else []
                if not any("默认目标" in str(item) for item in assumptions):
                    expected_errors.append("缺少目标时没有披露工作台默认目标")
            if run.spec.expected_target_qty is not None:
                actual = meta.get("target_qty")
                if actual is None or abs(float(actual) - run.spec.expected_target_qty) > 0.01:
                    expected_errors.append(
                        f"optimize.target_qty={actual!r}，期望 {run.spec.expected_target_qty:g}"
                    )
            if run.spec.expected_target_revenue is not None:
                actual = meta.get("target_revenue")
                if actual is None or abs(float(actual) - run.spec.expected_target_revenue) > 0.01:
                    expected_errors.append(
                        f"optimize.target_revenue={actual!r}，期望 {run.spec.expected_target_revenue:g}"
                    )
            chart_type = chart.get("type")
            card_types = [card.get("type") for card in cards if isinstance(card, dict)]
            if chart_type != "strategy_dashboard" or not {"strategy_matrix", "attainment_trend"} <= set(card_types):
                expected_errors.append("销售计划结果缺少 strategy_matrix + attainment_trend 工作台图表")
            matrix_card = next(
                (card for card in cards if isinstance(card, dict) and card.get("type") == "strategy_matrix"),
                {},
            )
            matrix_data = matrix_card.get("data") if isinstance(matrix_card.get("data"), dict) else {}
            if not isinstance(matrix_data.get("rows"), list) or not matrix_data.get("rows"):
                expected_errors.append("销售计划结果缺少策略推荐矩阵行")
            trend_card = next(
                (card for card in cards if isinstance(card, dict) and card.get("type") == "attainment_trend"),
                {},
            )
            trend_data = trend_card.get("data") if isinstance(trend_card.get("data"), dict) else {}
            for series_name in ("baseline", "target", "simulated"):
                series = trend_data.get(series_name) if isinstance(trend_data, dict) else None
                qty_values = series.get("qty") if isinstance(series, dict) else None
                if not isinstance(qty_values, list) or not any(value is not None for value in qty_values):
                    expected_errors.append(f"销售计划趋势缺少 {series_name}.qty")
    expected_errors.extend(_semantic_issues(run.spec, trace))

    if expected_errors and strict:
        run.errors.extend(expected_errors)
    else:
        run.warnings.extend(expected_errors)
    if not run.errors:
        run.ok = True

    del secret_values  # 保留形参让调用处显式说明输出受脱敏策略约束。


def run_case(
    client: httpx.Client,
    auth: AuthContext,
    spec: CaseSpec,
    *,
    session_id: str | None,
    timeout_s: float,
    strict: bool,
) -> CaseRun:
    run = CaseRun(spec=spec, prompt=spec.prompt)
    try:
        run.capture = stream_case(
            client,
            auth,
            spec,
            session_id=session_id,
            timeout_s=timeout_s,
        )
        if not isinstance(run.capture.result, dict):
            validate_run(run, strict=strict, secret_values=auth.secret_values)
            return run
        result_session_id = str(run.capture.result.get("session_id") or "")
        result_message_id = str(run.capture.result.get("message_id") or "")
        if result_session_id and result_message_id:
            run.session_id = result_session_id
            run.message_id = result_message_id
            run.trace, run.session_detail = fetch_trace_and_session(
                client,
                auth,
                result_session_id,
                result_message_id,
            )
        else:
            run.errors.append("无法回查 trace：result 缺少 session_id/message_id")
        validate_run(run, strict=strict, secret_values=auth.secret_values)
    except (httpx.HTTPError, ChatRequestError, ValueError) as exc:
        run.errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001
        run.errors.append(f"未预期异常：{type(exc).__name__}: {exc}")
    run.ok = not run.errors
    return run


def print_case(index: int, run: CaseRun, secret_values: Iterable[str], *, full_output: bool) -> None:
    print(f"\n[{index}] {run.spec.name}: {run.prompt}")
    if run.spec.note:
        print(f"  测试口径: {run.spec.note}")
    if run.capture is None:
        print("  状态: FAIL（未建立 SSE）")
    else:
        capture = run.capture
        print(
            f"  SSE: {_event_chain(capture.events)} | 首事件 {capture.first_event_ms or '-'}ms | 总耗时 {capture.elapsed_ms}ms"
        )
        stages = [str(item.get("stage") or "") for item in capture.statuses if item.get("stage")]
        print(f"  Agent 阶段: {_event_chain(stages)} | delta={len(capture.deltas)}")
        result = capture.result or {}
        steps = result.get("steps") if isinstance(result.get("steps"), list) else []
        if steps:
            print(f"  可观察步骤: {_compact(steps, secret_values, limit=1200)}")

        trace = run.trace or {}
        print(f"  Trace: session={run.session_id or '-'} message={run.message_id or '-'}")
        print(f"  Trace 事件: {_event_chain(str(item.get('type') or '') for item in trace.get('events', []))}")
        for event in trace.get("events", []):
            event_type = event.get("type")
            payload = event.get("payload", {})
            seq = event.get("seq", "-")
            if event_type == "tool_call":
                print(
                    f"    [{seq}] TOOL CALL {payload.get('name')}: "
                    f"input={_compact(payload.get('input', {}), secret_values, limit=4000 if full_output else 1200)}"
                )
            elif event_type == "tool_result":
                print(
                    f"    [{seq}] TOOL RESULT {payload.get('name')} status={payload.get('status')} "
                    f"duration={payload.get('duration_ms')}ms: "
                    f"output={_compact(payload.get('output'), secret_values, limit=12000 if full_output else 1800)}"
                )
            elif event_type == "tool_error":
                print(
                    f"    [{seq}] TOOL ERROR {payload.get('name')} code={payload.get('error_code')} "
                    f"message={_compact(payload.get('message'), secret_values, limit=800)}"
                )

        reply = result.get("reply", "")
        envelope = result.get("envelope", {})
        print(f"  Reply: {_compact(reply, secret_values, limit=12000 if full_output else 2400)}")
        print(f"  Envelope: {_compact(_envelope_summary(envelope, secret_values), secret_values, limit=12000 if full_output else 2200)}")

    if run.errors:
        print(f"  判定: FAIL — {'；'.join(run.errors)}")
    elif run.warnings:
        print(f"  判定: PASS（协议通过，期望链提示：{'；'.join(run.warnings)}）")
    else:
        print("  判定: PASS")


def case_report(run: CaseRun, secret_values: Iterable[str]) -> dict[str, Any]:
    capture = run.capture
    result = capture.result if capture else None
    return {
        "name": run.spec.name,
        "prompt": run.prompt,
        "expected": {
            "response_types": list(run.spec.expected_types),
            "required_tool_order": list(run.spec.required_tool_order),
            "forbidden_tools": list(run.spec.forbidden_tools),
            "minimum_tool_counts": {name: minimum for name, minimum in run.spec.min_tool_counts},
            "expected_target_qty": run.spec.expected_target_qty,
            "expected_target_revenue": run.spec.expected_target_revenue,
            "requires_default_target": run.spec.requires_default_target,
        },
        "ok": run.ok,
        "errors": list(run.errors),
        "warnings": list(run.warnings),
        "session_id": run.session_id,
        "message_id": run.message_id,
        "sse": {
            "events": list(capture.events) if capture else [],
            "statuses": _redact(capture.statuses, secret_values) if capture else [],
            "delta_count": len(capture.deltas) if capture else 0,
            "first_event_ms": capture.first_event_ms if capture else None,
            "elapsed_ms": capture.elapsed_ms if capture else None,
            "result": _redact(result, secret_values),
            "done": _redact(capture.done, secret_values) if capture else None,
        },
        "trace": _redact(run.trace, secret_values),
        "session_detail": _redact(run.session_detail, secret_values),
    }


def fetch_health(client: httpx.Client) -> dict[str, Any]:
    try:
        response = client.get("/api/health/agent")
        if response.status_code < 200 or response.status_code >= 300:
            return {"available": False, "error": _response_error(response)}
        payload = _response_payload(response)
        return payload if isinstance(payload, dict) else {"available": False, "error": "返回体不是对象"}
    except httpx.HTTPError as exc:
        return {"available": False, "error": str(exc)}


def require_real_provider(client: httpx.Client) -> dict[str, Any]:
    """强制检查 native engine 实际使用的 DB provider，而不是 ML gateway 配置。"""
    try:
        response = client.get("/healthz")
    except httpx.HTTPError as exc:
        raise ChatRequestError(f"无法检查 /healthz：{exc}") from exc
    payload = _json_object(response, "/healthz")
    llm = payload.get("checks", {}).get("llm", {})
    if llm.get("status") != "ok":
        raise ChatRequestError(
            "--require-real-llm 要求数据库默认 LLM provider 健康，"
            f"当前 checks.llm.status={llm.get('status')!r}"
        )
    return payload


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用真实 /api/chat/stream 并输出 LLM loop 的可观察规划与执行证据")
    parser.add_argument("--base-url", default=os.getenv("CHAT_BASE_URL", DEFAULT_BASE_URL), help="backend 地址")
    parser.add_argument("--access-token", help="本地 JWT；也可用 CHAT_ACCESS_TOKEN")
    parser.add_argument("--email", help="email 登录账号；也可用 CHAT_TEST_EMAIL")
    parser.add_argument("--password", help="email 登录密码；更推荐 CHAT_TEST_PASSWORD")
    parser.add_argument("--register", action="store_true", help="登录前尝试注册测试账号（仅开发库）")
    parser.add_argument("--oa", help="使用 OA 登录；也可用 CHAT_TEST_OA")
    parser.add_argument("--category", default=os.getenv("CHAT_TEST_CATEGORY", DEFAULT_CATEGORY), help="固定场景品类")
    parser.add_argument(
        "--forecast-month",
        type=_validate_month,
        default=os.getenv("CHAT_FORECAST_MONTH", _next_month()),
        help="预测基准月 YYYY-MM，默认运行时下一个自然月",
    )
    parser.add_argument(
        "--case",
        dest="cases",
        action="append",
        choices=("all", *CASE_NAMES),
        help="只运行指定场景；可重复传入，默认运行全部主场景",
    )
    parser.add_argument(
        "--question",
        dest="questions",
        action="append",
        help="直接测试自定义用户问题；可重复传入，不套用内置场景断言",
    )
    parser.add_argument("--include-follow-up", action="store_true", help="历史查询完成后复用同一 session 测试上下文追问")
    parser.add_argument("--strict", action="store_true", help="把期望的工具顺序/response_type 不匹配视为失败")
    parser.add_argument("--require-real-llm", action="store_true", help="要求 /healthz 的 native LLM provider status=ok")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="每个 SSE 场景的最长秒数")
    parser.add_argument("--report", type=Path, help="写入脱敏 JSON 报告；建议放在 /tmp 或未跟踪目录")
    parser.add_argument("--trace-dir", type=Path, help="额外保存 trace Markdown 的目录（默认不保存文件）")
    parser.add_argument("--full-output", action="store_true", help="控制台尽量展开工具结果；报告始终保存脱敏数据")
    parser.add_argument("--list-cases", action="store_true", help="只列出内置问题，不访问 backend")
    return parser


def selected_cases(args: argparse.Namespace, cases: dict[str, CaseSpec]) -> list[CaseSpec]:
    if args.questions:
        return [
            CaseSpec(name=f"custom-{index}", prompt=question, note="自定义问题：只验证真实 SSE、trace 和最终 envelope。")
            for index, question in enumerate(args.questions, start=1)
        ]
    requested = args.cases or ["all"]
    if "all" in requested:
        return [cases[name] for name in DEFAULT_CASE_NAMES]
    return [cases[name] for name in requested]


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.timeout <= 0:
        print("--timeout 必须大于 0", file=sys.stderr)
        return 2
    cases = build_cases(args.category, args.forecast_month)
    if args.list_cases:
        for name, spec in cases.items():
            print(f"{name}: {spec.prompt} | {spec.note}")
        print("follow-up: 把时间范围改为最近3个月（复用 history session）")
        return 0

    try:
        timeout = httpx.Timeout(connect=10.0, read=args.timeout, write=30.0, pool=10.0)
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            timeout=timeout,
            trust_env=False,
        ) as client:
            health = fetch_health(client)
            print("=== Chat request live test ===")
            print(f"backend: {args.base_url.rstrip('/')}")
            print(f"health: mode={health.get('mode', '-')} provider={health.get('provider', '-')} ok={health.get('ok', '-')}")
            if args.require_real_llm:
                health = {**health, "native_healthz": require_real_provider(client)}
                print("native LLM provider: healthy")

            auth = authenticate(client, args)
            print("auth: ok（凭据不打印）")
            print(f"category: {args.category} | forecast_month: {args.forecast_month} | timeout: {args.timeout:.0f}s")
            if health.get("mode") in {"disabled", None}:
                print("warning: 当前 /api/health/agent 未显示 live/provider；native engine 可能走 MockProvider。")

            runs: list[CaseRun] = []
            history_session: str | None = None
            for index, spec in enumerate(selected_cases(args, cases), start=1):
                run = run_case(
                    client,
                    auth,
                    spec,
                    session_id=None,
                    timeout_s=args.timeout,
                    strict=args.strict,
                )
                runs.append(run)
                print_case(index, run, auth.secret_values, full_output=args.full_output)
                if spec.name == "history" and run.ok:
                    history_session = run.session_id

            if args.include_follow_up:
                if history_session is None:
                    history_spec = cases["history"]
                    history_run = run_case(
                        client,
                        auth,
                        history_spec,
                        session_id=None,
                        timeout_s=args.timeout,
                        strict=args.strict,
                    )
                    history_session = history_run.session_id
                    history_index = len(runs) + 1
                    runs.append(history_run)
                    print_case(history_index, history_run, auth.secret_values, full_output=args.full_output)
                follow_spec = CaseSpec(
                    name="follow-up",
                    prompt="把时间范围改为最近3个月",
                    expected_types=("history",),
                    required_tool_order=("get_history",),
                    note="验证历史会话上下文可被下一轮使用。",
                )
                follow_run = run_case(
                    client,
                    auth,
                    follow_spec,
                    session_id=history_session,
                    timeout_s=args.timeout,
                    strict=args.strict,
                )
                follow_index = len(runs) + 1
                runs.append(follow_run)
                print_case(follow_index, follow_run, auth.secret_values, full_output=args.full_output)

            if args.trace_dir:
                args.trace_dir.mkdir(parents=True, exist_ok=True)
                for run in runs:
                    if not run.trace or not run.session_id or not run.message_id:
                        continue
                    response = client.get(
                        f"/api/v1/chat/conversations/{run.session_id}/messages/{run.message_id}/trace/export",
                        headers=auth.headers,
                    )
                    if response.status_code < 200 or response.status_code >= 300:
                        run.warnings.append(f"trace Markdown 导出失败：{_response_error(response, auth.secret_values)}")
                        continue
                    path = args.trace_dir / f"{run.spec.name}-{run.message_id}.md"
                    path.write_text(_redact(response.text, auth.secret_values), encoding="utf-8")
                    print(f"  trace export: {path}")

            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "base_url": args.base_url.rstrip("/"),
                "health": _redact(health, auth.secret_values),
                "strict": args.strict,
                "category": args.category,
                "forecast_month": args.forecast_month,
                "cases": [case_report(run, auth.secret_values) for run in runs],
            }
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"report: {args.report}")

            failed = sum(1 for run in runs if not run.ok)
            warned = sum(1 for run in runs if run.warnings)
            print(f"\n=== SUMMARY: total={len(runs)} passed={len(runs) - failed} failed={failed} warned={warned} ===")
            return 1 if failed else 0
    except (ChatRequestError, httpx.HTTPError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
