"""T02 配置模块：pydantic-settings 全量环境变量。

对齐 tech_design §7.3 环境变量清单与 §3.11.5 系统参数键。
业务代码一律经 get_settings() 读取；system_config 热更新键由领域模块叠加读取，
本模块提供配置缓存失效原语 invalidate_config_key（供 T20 PATCH /admin/config 使用）。
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: system_config 中可热更新的键清单（tech_design §3.11.5 表格全量）
CACHED_KEYS: tuple[str, ...] = (
    "retention.conversation_days",
    "retention.audit_days",
    "auth.email_whitelist_suffixes",
    "auth.login_fail_limit",
    "sandbox.max_concurrent",
    "sandbox.timeout_s",
    "llm.default_provider_id",
    "llm.default_model",
    "conversation.user_max_messages",
)


class Settings(BaseSettings):
    """应用全部环境变量。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 数据库 ---
    database_url: str  # 必填

    # --- 认证/密钥 ---
    jwt_secret: str  # 必填，>=32 字节
    admin_initial_email: str = ""
    admin_initial_password: str = ""

    # --- OA OAuth 网关 ---
    oauth_base_url: str = "https://aigc-gateway.tcl.com"
    oauth_token_path: str = "/oauth/oauth/token"
    oauth_grant_type: str = "username"
    oauth_client_id: str = "ai-client"
    oauth_client_secret: str = "secret"
    oauth_source_type: str = "app"
    oauth_user_type: str = "P"
    oauth_login_field: str = "username"
    oauth_device_id: str = ""

    # --- 沙箱 daemon ---
    api_internal_token: str  # 必填，daemon 互认密钥
    sandbox_daemon_url: str = "http://127.0.0.1:9000"

    # --- LLM 供应商（分号分隔首个 provider key；另两项为同维度首个 provider 的 base_url / 默认模型，留空则跳过 seed 首建）---
    llm_api_keys: str = ""
    llm_base_url: str = ""
    llm_default_model: str = ""

    # --- 内网数据服务 token ---
    internal_token: str = ""

    # --- 沙箱出网白名单（逗号分隔 CIDR / 域名后缀）---
    whitelist_cidrs: str = "10.0.0.0/8,192.168.0.0/16"

    # --- 通用 ---
    sandbox_timeout_s: int = 30
    log_level: str = "INFO"
    api_base_url: str = "http://127.0.0.1:8000"
    icewash_base_url: str = "http://127.0.0.1:8001"
    workbench_sync_on_startup: bool = False

    # --- 预测模型（T06；目标模型服务是唯一上游） ---
    forecast_model_enabled: bool = True
    forecast_model_base_url: str = "http://127.0.0.1:8001"
    forecast_model_output_dir: str = ""
    forecast_category_batch_map_json: str = "{}"
    forecast_default_product_line: str = "PL003"
    forecast_reporter: str = "forecast-agent"
    forecast_poll_interval_sec: float = 5.0
    forecast_poll_timeout_sec: float = 3600.0

    # --- Agent LLM gateway (T08; independent from the backup LLM provider loop) ---
    agent_api_url: str = "https://ml-api-gw-en.tcl.com/agi/v1/chat-messages"
    agent_api_key: str = ""
    agent_response_mode: str = "blocking"
    agent_timeout_sec: float = 120.0
    agent_user: str = "forecast-agent-ui"
    agent_oa: str = ""
    agent_enable_thinking: str = ""
    agent_attachment: str = ""
    agent_extra_inputs_json: str = ""
    analysis_agent_enabled: bool = True
    turing_api_base: str = "https://live-turing.cn.llm.tcljd.com/api/v1"
    turing_api_key: str = ""
    turing_model: str = "turing/gpt-5.4-mini"
    turing_timeout_sec: float = 90.0

    # --- 可选开发参数 ---
    cors_origins: str = "*"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    @field_validator("jwt_secret")
    @classmethod
    def _check_jwt_secret_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET 长度必须 >=32 字节（HS256 安全要求）")
        return v

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL 必须为 postgresql(+driver):// 形式")
        return v

    @field_validator("whitelist_cidrs")
    @classmethod
    def _normalize_whitelist(cls, v: str) -> str:
        # 允许以逗号/空格/分号分隔，归一为逗号分隔
        parts = [p.strip() for p in re.split(r"[,;\s]+", v) if p.strip()]
        return ",".join(parts)

    # ------------------------------------------------------------------
    # 便捷派生
    # ------------------------------------------------------------------
    @property
    def whitelist_list(self) -> list[str]:
        return [p for p in self.whitelist_cidrs.split(",") if p]

    @property
    def llm_api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.llm_api_keys.split(";") if k.strip()]

    @property
    def has_llm_bootstrap(self) -> bool:
        """具备首个 LLM provider 的环境引导信息（key + base_url 齐备才可建）。"""
        return bool(self.llm_api_keys_list and self.llm_base_url.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """模块级配置单例（进程启动后固定）。"""
    return Settings()


def reset_settings() -> None:
    """测试用：清缓存，重建 Settings。"""
    get_settings.cache_clear()


# ------------------------------------------------------------------
# 系统参数热更新缓存失效原语
# ------------------------------------------------------------------
# 领域模块可能用进程内变量缓存 system_config 键值；PATCH 后调用本函数清缓存。
_key_caches: dict[str, Any] = {}


def invalidate_config_key(key: str) -> None:
    """系统参数更新后失效对应键的缓存（T20 PATCH /admin/config 调用）。"""
    _key_caches.pop(key, None)


def get_cached_config(key: str) -> Any:
    """读取某键缓存的占位（T20 具体叠加逻辑在各领域模块实现）。"""
    return _key_caches.get(key)
