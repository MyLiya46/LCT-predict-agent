"""LLMProvider 协议与 factory（T09）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from app.llm.events import ProviderUnavailable, StreamEvent


class LLMProvider(ABC):
    """统一聊天接口：chat(messages, tools, config) → AsyncIterator[StreamEvent]。"""

    name: str = "base"
    provider_id: Optional[str] = None
    configured: bool = True

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError

    @abstractmethod
    async def check_health(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
    ) -> str:
        """一次性非流式补全（轻量任务：T32 follow-up 建议生成等）。失败抛 ProviderUnavailable。"""
        raise NotImplementedError


def get_provider(provider_record: Any, api_key: str) -> LLMProvider:
    """按 vendor 构造 provider。

    Args:
        provider_record: llm_providers 表行（含 id/name/vendor/base_url/default_model）
        api_key: 解密后的 key
    """
    from app.llm.adapter_openai import OpenAICompatProvider

    vendor = getattr(provider_record, "vendor", "openai_compat")
    if vendor != "openai_compat":
        raise ValueError(f"暂不支持的供应商类型: {vendor}")
    provider = OpenAICompatProvider(
        provider_id=str(provider_record.id),
        name=provider_record.name,
        base_url=provider_record.base_url,
        api_key=api_key,
        default_model=provider_record.default_model,
        status=getattr(provider_record, "status", "healthy"),
    )
    if provider.status == "unhealthy":
        raise ProviderUnavailable("该供应商当前不可用", provider_id=str(provider_record.id))
    return provider
