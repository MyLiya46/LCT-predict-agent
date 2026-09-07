"""Async client for the target icewash prediction model (T06).

The backend deliberately knows only the model HTTP API.  Persisted forecast
rows are read from the model-owned ``fcst_*`` relay tables after a successful
task; the Excel file is an offline compatibility path only.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from app.config import Settings, get_settings

REQUEST_TIMEOUT_SECONDS = 30.0
_MONTH_RE = re.compile(r"^(?P<year>\d{4})[-/]?(?P<month>\d{1,2})(?:[-/]?(?:\d{1,2}))?$")

# The Agent occasionally emits the stable English identifiers instead of the
# Chinese category names used by the model service and relay tables.  Keep the
# normalization at the model boundary so every caller (API, internal tool,
# and retry) shares the same deterministic run key.
_CATEGORY_ALIASES = {
    "refrigerator": "冰箱",
    "fridge": "冰箱",
    "icebox": "冰箱",
    "washing_machine": "洗衣机",
    "washing-machine": "洗衣机",
    "washing machine": "洗衣机",
    "washer": "洗衣机",
}


class ForecastModelError(RuntimeError):
    """An upstream model request or task result is not usable."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _normalize_month(value: str | None) -> str:
    """Normalize a month/date to the model's ``YYYY-MM-01`` contract."""
    if value is None or not str(value).strip():
        now = datetime.now()
        return f"{now.year:04d}-{now.month:02d}-01"
    text = str(value).strip()
    match = _MONTH_RE.match(text)
    if not match:
        raise ValueError(f"forecast_month 必须为 YYYY-MM 或 YYYY-MM-DD: {value}")
    month = int(match.group("month"))
    if month < 1 or month > 12:
        raise ValueError(f"forecast_month 月份非法: {value}")
    return f"{match.group('year')}-{month:02d}-01"


def _month_key(value: str | None) -> str:
    return _normalize_month(value)[:7]


def normalize_category(value: str) -> str:
    """Return the model's canonical category label for common Agent aliases."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("category 不能为空")
    lookup = re.sub(r"\s+", " ", text.casefold())
    return _CATEGORY_ALIASES.get(lookup, text)


def _load_batch_map(raw: str | Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    value: Any = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("FORECAST_CATEGORY_BATCH_MAP_JSON 不是合法 JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("FORECAST_CATEGORY_BATCH_MAP_JSON 必须是品类到批次的对象")
    result: dict[str, dict[str, str]] = {}
    for category, item in value.items():
        if not isinstance(item, Mapping):
            raise ValueError(f"品类 {category} 的批次配置必须是对象")
        price = item.get("priceBatchNumber") or item.get("price_batch_number")
        product = item.get("productBatchNumber") or item.get("product_batch_number")
        if not price or not product:
            raise ValueError(f"品类 {category} 缺少 priceBatchNumber/productBatchNumber")
        result[str(category)] = {
            "priceBatchNumber": str(price),
            "productBatchNumber": str(product),
        }
    return result


def resolve_output_dir(settings: Settings | None = None) -> Path:
    """Return the configured model output directory, with the fixed T06 default."""
    settings = settings or get_settings()
    if settings.forecast_model_output_dir.strip():
        return Path(settings.forecast_model_output_dir).expanduser().resolve()
    # app/config.py -> backend/src/app -> repository root
    return Path(__file__).resolve().parents[4] / "services" / "icewash-model"


def output_path_for(system_forecast_number: str, settings: Settings | None = None) -> Path:
    if not system_forecast_number or Path(system_forecast_number).name != system_forecast_number:
        raise ValueError("system_forecast_number 非法")
    return resolve_output_dir(settings) / f"output_{system_forecast_number}.xlsx"


def run_key(category: str, forecast_month: str | None, horizon: int | None = None) -> str:
    """Stable idempotency key for a category/month/horizon run.

    Calls that omit ``horizon`` keep the historical category/month identifier
    for workbook and API compatibility.  Agent/model runs include the
    requested horizon so a completed three-month task cannot satisfy a later
    seven-month request for the same base month.
    """
    category = normalize_category(category)
    key = f"AG_{category}_{_month_key(forecast_month)}"
    if horizon is None:
        return key
    try:
        normalized_horizon = int(horizon)
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon 必须是 1 到 12 的整数") from exc
    if not 1 <= normalized_horizon <= 12:
        raise ValueError("horizon 必须是 1 到 12 的整数")
    return f"{key}-H{normalized_horizon}"


def _build_payload(
    *,
    category: str,
    forecast_month: str | None = None,
    forecast_horizon: int | None = None,
    settings: Settings | None = None,
    system_forecast_number: str | None = None,
    product_line: str | None = None,
    reporter: str | None = None,
    generate_time: str | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    batch_map = _load_batch_map(settings.forecast_category_batch_map_json)
    category = normalize_category(category)
    # Also tolerate a configured map that uses an equivalent spelling/case.
    # The configured key remains authoritative in the upstream payload.
    if category not in batch_map:
        for configured in batch_map:
            if normalize_category(configured).casefold() == category.casefold():
                category = configured
                break
    if category not in batch_map:
        raise ValueError(f"未配置品类批次号: {category}")
    number = system_forecast_number or run_key(category, forecast_month, forecast_horizon)
    payload = {
        "systemForecastNumber": number,
        "productLine": product_line or settings.forecast_default_product_line,
        "reporter": reporter or settings.forecast_reporter,
        "generateTime": generate_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "customCallbackUrl": None,
        "forecastMonth": _normalize_month(forecast_month),
        "saveTestData": False,
        "categoryBatchMappingDTOList": [{"category": category, **batch_map[category]}],
    }
    if forecast_horizon is not None:
        payload["forecastHorizon"] = int(forecast_horizon)
    return payload


class ForecastModelClient:
    """Small, testable async wrapper around the target model endpoints."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._runs: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        return self.settings.forecast_model_base_url.rstrip("/")

    def _build_payload(self, **kwargs: Any) -> dict[str, Any]:
        return _build_payload(settings=self.settings, **kwargs)

    async def _request(self, method: str, path: str, *, json_body: Any = None) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False)
        try:
            try:
                response = await client.request(method, f"{self.base_url}{path}", json=json_body)
            except httpx.HTTPError as exc:
                raise ForecastModelError(f"预测模型不可达: {exc}") from exc
            try:
                payload = response.json()
            except ValueError as exc:
                payload = None
                raise ForecastModelError(
                    f"预测模型返回非法 JSON (HTTP {response.status_code})",
                    status_code=response.status_code,
                ) from exc
            if response.is_error:
                detail = payload.get("detail") if isinstance(payload, Mapping) else payload
                raise ForecastModelError(
                    f"预测模型请求失败 (HTTP {response.status_code}): {detail}",
                    status_code=response.status_code,
                    payload=payload,
                )
            if not isinstance(payload, dict):
                raise ForecastModelError("预测模型返回格式非法", status_code=response.status_code)
            return payload
        finally:
            if owns_client:
                await client.aclose()

    async def submit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/predict", json_body=dict(payload))

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/tasks/{task_id}")

    async def list_tasks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        payload = await self._request("GET", f"/tasks?limit={max(1, min(limit, 200))}")
        tasks = payload.get("tasks")
        return [dict(item) for item in tasks if isinstance(item, Mapping)] if isinstance(tasks, list) else []

    @staticmethod
    def _task_success(task: Mapping[str, Any]) -> bool:
        result = task.get("result")
        if not isinstance(result, Mapping):
            return False
        data = result.get("data")
        pg_write = result.get("pg_write")
        return (
            task.get("status") == "completed"
            and isinstance(data, Mapping)
            and data.get("saved_success") is True
            and isinstance(pg_write, Mapping)
            and int(pg_write.get("forecast_rows") or 0) > 0
            and int(pg_write.get("attribution_rows") or 0) > 0
        )

    def validate_completed(self, task: Mapping[str, Any]) -> dict[str, Any]:
        if task.get("status") == "failed":
            raise ForecastModelError(str(task.get("error_message") or "预测模型任务失败"), payload=task)
        if not self._task_success(task):
            raise ForecastModelError(
                "预测模型任务完成但结果未通过 saved_success/PG 行数校验",
                payload=task,
            )
        return dict(task)

    async def poll_events(
        self,
        task_id: str,
        *,
        progress_callback: Callable[[Mapping[str, Any]], Awaitable[None] | None] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield task snapshots until a terminal status or timeout is reached."""
        started = asyncio.get_running_loop().time()
        while True:
            task = await self.get_task(task_id)
            yield task
            if progress_callback is not None:
                callback_result = progress_callback(task)
                if inspect.isawaitable(callback_result):
                    await callback_result
            status = task.get("status")
            if status in {"completed", "failed", "cancelled"}:
                return
            if asyncio.get_running_loop().time() - started >= self.settings.forecast_poll_timeout_sec:
                raise ForecastModelError(f"预测模型任务超时: {task_id}", payload=task)
            await asyncio.sleep(max(0.0, self.settings.forecast_poll_interval_sec))

    async def refresh(
        self,
        task_id: str,
        *,
        wait: bool = True,
        progress_callback: Callable[[Mapping[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        if not wait:
            return await self.get_task(task_id)
        latest: dict[str, Any] | None = None
        async for latest in self.poll_events(task_id, progress_callback=progress_callback):
            pass
        assert latest is not None
        return self.validate_completed(latest)

    async def ensure_run(
        self,
        *,
        category: str,
        forecast_month: str | None = None,
        wait: bool = True,
        horizon: int | None = None,
        progress_callback: Callable[[Mapping[str, Any]], Awaitable[None] | None] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        number = run_key(category, forecast_month, horizon)
        task_id = self._runs.get(number)
        if task_id:
            try:
                task = await self.refresh(task_id, wait=wait, progress_callback=progress_callback)
            except ForecastModelError as exc:
                payload = exc.payload
                terminal_failure = isinstance(payload, Mapping) and payload.get("status") in {"failed", "cancelled"}
                if not terminal_failure:
                    raise
                self._runs.pop(number, None)
            else:
                if task.get("status") == "completed":
                    return {"system_forecast_number": number, "task": task, "reused": True}
        else:
            # The model persists tasks across its own restarts.  Re-discover a
            # task by its deterministic run key so a backend restart cannot
            # submit a duplicate prediction.
            try:
                summaries = await self.list_tasks()
            except ForecastModelError:
                # Some older model builds expose /tasks but fail while
                # serializing their persisted store.  Discovery is an
                # optimization; it must never prevent a normal submission.
                summaries = []
            for summary in summaries:
                if summary.get("systemForecastNumber") != number:
                    continue
                discovered = str(summary.get("task_id") or "")
                if not discovered:
                    continue
                self._runs[number] = discovered
                try:
                    task = await self.refresh(discovered, wait=wait, progress_callback=progress_callback)
                except ForecastModelError as exc:
                    payload = exc.payload
                    terminal_failure = isinstance(payload, Mapping) and payload.get("status") in {"failed", "cancelled"}
                    if not terminal_failure:
                        raise
                    self._runs.pop(number, None)
                else:
                    if task.get("status") == "completed":
                        return {"system_forecast_number": number, "task": task, "reused": True}
                break
        payload = _build_payload(
            category=category,
            forecast_month=forecast_month,
            settings=self.settings,
            system_forecast_number=number,
            product_line=kwargs.get("product_line"),
            reporter=kwargs.get("reporter"),
            generate_time=kwargs.get("generate_time"),
            forecast_horizon=horizon,
        )
        submitted = await self.submit(payload)
        task_id = str(submitted.get("task_id") or "")
        if not task_id:
            raise ForecastModelError("预测模型提交响应缺少 task_id", payload=submitted)
        self._runs[number] = task_id
        task = await self.refresh(task_id, wait=wait, progress_callback=progress_callback)
        return {"system_forecast_number": number, "task": task, "reused": False}


_default_client: ForecastModelClient | None = None


def get_forecast_model_client() -> ForecastModelClient:
    global _default_client
    settings = get_settings()
    if _default_client is None or _default_client.settings is not settings:
        _default_client = ForecastModelClient(settings)
    return _default_client


async def submit(payload: Mapping[str, Any]) -> dict[str, Any]:
    return await get_forecast_model_client().submit(payload)


async def get_task(task_id: str) -> dict[str, Any]:
    return await get_forecast_model_client().get_task(task_id)


async def refresh(
    task_id: str,
    *,
    wait: bool = True,
    progress_callback: Callable[[Mapping[str, Any]], Awaitable[None] | None] | None = None,
) -> dict[str, Any]:
    return await get_forecast_model_client().refresh(task_id, wait=wait, progress_callback=progress_callback)


async def ensure_run(**kwargs: Any) -> dict[str, Any]:
    return await get_forecast_model_client().ensure_run(**kwargs)


async def poll_events(task_id: str) -> AsyncIterator[dict[str, Any]]:
    async for event in get_forecast_model_client().poll_events(task_id):
        yield event


__all__ = [
    "ForecastModelClient", "ForecastModelError", "_build_payload", "_load_batch_map",
    "_normalize_month", "ensure_run", "get_forecast_model_client", "get_task", "output_path_for",
    "poll_events", "refresh", "resolve_output_dir", "run_key", "submit",
]
