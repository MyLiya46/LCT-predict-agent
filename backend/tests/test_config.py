"""T02 配置模块单测：必填校验、默认值、env 覆盖。"""

import os

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings, reset_settings


def test_required_fields_missing():
    """缺失数据库地址 / 过短 JWT 密钥 → 校验错误。"""
    with pytest.raises(ValidationError):
        Settings(database_url="")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+asyncpg://u:p@localhost:5432/db", jwt_secret="short")


def test_defaults():
    reset_settings()
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://app:pwd@localhost:5432/agent_platform"
    os.environ["JWT_SECRET"] = "x" * 40
    os.environ["API_INTERNAL_TOKEN"] = "tok"
    os.environ["ADMIN_INITIAL_EMAIL"] = ""
    os.environ["ADMIN_INITIAL_PASSWORD"] = ""
    # 绕过 backend/.env 干扰：_env_file 置空
    import pydantic_settings  # noqa: F401
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.sandbox_timeout_s == 30
    assert s.log_level == "INFO"
    assert s.admin_initial_email == ""
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("JWT_SECRET", None)
    os.environ.pop("API_INTERNAL_TOKEN", None)
    os.environ.pop("ADMIN_INITIAL_EMAIL", None)
    os.environ.pop("ADMIN_INITIAL_PASSWORD", None)
    reset_settings()


def test_env_override():
    reset_settings()
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://app:pwd@localhost:5432/agent_platform"
    os.environ["JWT_SECRET"] = "y" * 40
    os.environ["API_INTERNAL_TOKEN"] = "tok"
    os.environ["SANDBOX_TIMEOUT_S"] = "45"
    os.environ["LLM_API_KEYS"] = "k1;k2"
    os.environ["WHITELIST_CIDRS"] = "10.0.0.0/8 172.16.0.0/12"
    s = get_settings()
    assert s.sandbox_timeout_s == 45
    assert s.llm_api_keys_list == ["k1", "k2"]
    assert s.whitelist_list == ["10.0.0.0/8", "172.16.0.0/12"]
    for k in ("DATABASE_URL", "JWT_SECRET", "API_INTERNAL_TOKEN", "SANDBOX_TIMEOUT_S", "WHITELIST_CIDRS"):
        os.environ.pop(k, None)
    # 恢复测试基线（conftest 的 LLM 引导变量清空；此前被本测试覆盖）
    os.environ["LLM_API_KEYS"] = ""
    os.environ["LLM_BASE_URL"] = ""
    os.environ["LLM_DEFAULT_MODEL"] = ""
    reset_settings()