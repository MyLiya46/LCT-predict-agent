"""内置工具执行加载器（T43 / tech_design §3.14 非沙箱分支）。

internal 工具约定：`tools/internal/<name>/tool.py` 暴露 `async def handle(input) -> dict`，
进程内直接调用，不走 sandbox daemon、不写 sandbox_instances。
"""
from __future__ import annotations

import importlib
from typing import Any

from app.utils.errors import ValidationError


async def run_internal(
    name: str,
    input_data: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> Any:
    """动态加载并调用内建工具 handler；异常交由引擎归一为 error 事件。"""
    try:
        mod = importlib.import_module(f"app.tools.internal.{name}.tool")
    except ImportError as exc:
        raise ValidationError(f"internal 工具 {name} 未实现: {exc}") from exc
    handler = getattr(mod, "handle", None)
    if handler is None:
        raise ValidationError(f"internal 工具 {name} 缺少 handle(input)")
    # Keep the one-argument handler contract valid for existing internal
    # tools, while allowing capability tools to receive the current PG
    # session and test/client adapters without putting them in tool JSON.
    try:
        return await handler(input_data, context)
    except TypeError as exc:
        try:
            return await handler(input_data)
        except TypeError:
            raise exc
