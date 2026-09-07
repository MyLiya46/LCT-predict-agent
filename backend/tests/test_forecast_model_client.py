from __future__ import annotations

import pytest

from app.config import Settings
from app.services.forecast_model_client import (
    ForecastModelClient,
    _build_payload,
    _load_batch_map,
    _normalize_month,
    normalize_category,
    output_path_for,
    run_key,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://app:app@localhost/db",
        jwt_secret="x" * 40,
        api_internal_token="token",
        forecast_category_batch_map_json='{"冰箱":{"priceBatchNumber":"P-1","productBatchNumber":"S-1"}}',
    )


def test_month_batch_payload_and_run_key():
    settings = _settings()
    assert _normalize_month("2026-08") == "2026-08-01"
    assert _load_batch_map(settings.forecast_category_batch_map_json)["冰箱"]["priceBatchNumber"] == "P-1"
    payload = _build_payload(category="冰箱", forecast_month="2026-08", settings=settings)
    assert payload["systemForecastNumber"] == "AG_冰箱_2026-08"
    assert payload["forecastMonth"] == "2026-08-01"
    assert payload["customCallbackUrl"] is None
    assert payload["saveTestData"] is False
    assert payload["categoryBatchMappingDTOList"] == [
        {"category": "冰箱", "priceBatchNumber": "P-1", "productBatchNumber": "S-1"}
    ]
    horizon_payload = _build_payload(
        category="冰箱", forecast_month="2026-08", forecast_horizon=3, settings=settings
    )
    assert horizon_payload["systemForecastNumber"] == "AG_冰箱_2026-08-H3"
    assert horizon_payload["forecastHorizon"] == 3
    assert run_key("冰箱", "2026-08-01") == "AG_冰箱_2026-08"
    assert run_key("冰箱", "2026-08-01", 3) == "AG_冰箱_2026-08-H3"


def test_agent_category_aliases_use_canonical_model_key():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://app:app@localhost/db",
        jwt_secret="x" * 40,
        api_internal_token="token",
        forecast_category_batch_map_json=(
            '{"冰箱":{"priceBatchNumber":"P-1","productBatchNumber":"S-1"},'
            '"洗衣机":{"priceBatchNumber":"P-2","productBatchNumber":"S-2"}}'
        ),
    )
    assert normalize_category("washing_machine") == "洗衣机"
    assert run_key("washing_machine", "2026-09") == "AG_洗衣机_2026-09"
    payload = _build_payload(category="washing_machine", forecast_month="2026-09", settings=settings)
    assert payload["categoryBatchMappingDTOList"][0]["category"] == "洗衣机"


def test_default_output_dir_is_model_root():
    assert "services" in str(output_path_for("AG_冰箱_2026-08"))
    assert str(output_path_for("AG_冰箱_2026-08")).endswith("output_AG_冰箱_2026-08.xlsx")


def test_invalid_batch_map_and_failed_task():
    settings = _settings()
    with pytest.raises(ValueError):
        _build_payload(category="洗衣机", forecast_month="2026-08", settings=settings)
    client = ForecastModelClient(settings)
    with pytest.raises(RuntimeError, match="任务失败"):
        client.validate_completed({"status": "failed", "error_message": "任务失败"})
