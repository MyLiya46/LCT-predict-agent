"""工具 schema 与白名单声明校验（T14 / tech_design §3.5）。"""
from __future__ import annotations

import re
from typing import Any

import jsonschema

from app.utils.errors import ValidationError

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def validate_tool_schema(input_schema: dict[str, Any], output_schema: dict[str, Any]) -> None:
    """强制输入 schema 合法且满足约束（type=object / required 存在 / additionalProperties=false）。"""
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        raise ValidationError("input_schema.type 必须为 'object'")
    if not input_schema.get("properties"):
        raise ValidationError("input_schema 必须包含 properties")
    if "required" not in input_schema:
        input_schema["required"] = list(input_schema.get("properties", {}).keys())
    input_schema.setdefault("additionalProperties", False)
    if input_schema.get("additionalProperties") is not False:
        raise ValidationError("input_schema.additionalProperties 必须为 false")
    # 自校验（检查 schema 本身合法 JSON Schema，而非对空实例验数据）
    try:
        jsonschema.Draft202012Validator.check_schema(input_schema)
    except jsonschema.SchemaError as exc:
        raise ValidationError(f"input_schema 非法 JSON Schema: {exc}") from exc

    if output_schema:
        try:
            jsonschema.Draft202012Validator.check_schema(output_schema)
        except jsonschema.SchemaError as exc:
            raise ValidationError(f"output_schema 非法 JSON Schema: {exc}") from exc


def validate_execution(execution: dict[str, Any]) -> None:
    """execution 结构校验（kind ∈ {sandbox, internal}，T43 起支持 internal）。"""
    kind = execution.get("kind", "sandbox")
    if kind == "internal":
        _validate_internal_execution(execution)
        return
    if kind != "sandbox":
        raise ValidationError("execution.kind 仅支持 'sandbox' / 'internal'")

    image = execution.get("image")
    if not image or not isinstance(image, str):
        raise ValidationError("execution.image 必填")
    handler = execution.get("handler")
    if not handler or not isinstance(handler, str):
        raise ValidationError("execution.handler 必填")
    timeout_s = execution.get("timeout_s", 30)
    if not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ValidationError("execution.timeout_s 必须为正整数")
    warm_pool = execution.get("warm_pool", 0)
    if not isinstance(warm_pool, int) or warm_pool < 0:
        raise ValidationError("execution.warm_pool 必须为非负整数")

    ds_refs = execution.get("env_from_datasource", [])
    if not isinstance(ds_refs, list):
        raise ValidationError("execution.env_from_datasource 必须为数组")


def _validate_internal_execution(execution: dict[str, Any]) -> None:
    """T43：internal 工具（进程内，无镜像/预热池/数据源注入）。"""
    handler = execution.get("handler")
    if not handler or not isinstance(handler, str):
        raise ValidationError("internal 工具 execution.handler 必填")
    timeout_s = execution.get("timeout_s", 5)
    if not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ValidationError("execution.timeout_s 必须为正整数")
    ds_refs = execution.get("env_from_datasource", [])
    if ds_refs:
        raise ValidationError("internal 工具不支持 env_from_datasource（进程内执行，无容器注入）")


def validate_tool_name(name: str) -> None:
    if not TOOL_NAME_RE.match(name):
        raise ValidationError("工具名必须为 [a-z][a-z0-9_]{1,63} 蛇形命名")
