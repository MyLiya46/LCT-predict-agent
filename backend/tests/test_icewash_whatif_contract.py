from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "icewash-model"
    / "cbg_fcst_month"
    / "whatif.py"
)
SPEC = importlib.util.spec_from_file_location("icewash_whatif_engine", MODEL_PATH)
assert SPEC and SPEC.loader
whatif = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(whatif)


def _load_server_request_models():
    """Load only server Pydantic models without importing the model pipeline dependencies."""
    model_dir = MODEL_PATH.parent
    module_name = "_t27_icewash_server"
    fake_modules = {}

    main_module = types.ModuleType("main")
    main_module.main = lambda *args, **kwargs: None
    fake_modules["main"] = main_module

    config_module = types.ModuleType("config")

    class Config:
        LOG_DIR = str(model_dir / "log")
        CALLBACK_BASE_URL = "http://127.0.0.1:8001"
        ORGANIZATION_ID = "test"

    config_module.Config = Config
    fake_modules["config"] = config_module

    request_log_module = types.ModuleType("request_log")
    request_log_module.RequestLogSession = object
    request_log_module.make_request_log_path = lambda *args, **kwargs: model_dir / "test.log"
    fake_modules["request_log"] = request_log_module

    reference_module = types.ModuleType("reference_data")
    reference_module.REFERENCE_DIR = model_dir
    reference_module.ReferenceDataError = type("ReferenceDataError", (Exception,), {})
    reference_module._source_for = lambda path: str(path)
    reference_module.knowledge_markdown = lambda: ""
    reference_module.load_workbench_dataset = lambda dataset: {}
    reference_module.parse_cost_upload = lambda content, filename: ([], [], None)
    fake_modules["reference_data"] = reference_module

    whatif_module = types.ModuleType("whatif")
    whatif_module.strategies_response = lambda status=None: {}
    whatif_module.resolve_ed = lambda *args: 1.0
    whatif_module.simulate_row = lambda **kwargs: {}
    whatif_module.search_optimize = lambda **kwargs: {}
    fake_modules["whatif"] = whatif_module

    previous_modules = {name: sys.modules.get(name) for name in fake_modules}
    previous_path = list(sys.path)
    sys.modules.update(fake_modules)
    sys.path.insert(0, str(model_dir))
    try:
        server_spec = importlib.util.spec_from_file_location(module_name, model_dir / "server.py")
        assert server_spec and server_spec.loader
        server = importlib.util.module_from_spec(server_spec)
        sys.modules[module_name] = server
        server_spec.loader.exec_module(server)
        return server.SimulateRequest, server.OptimizeRequest
    finally:
        sys.path[:] = previous_path
        sys.modules.pop(module_name, None)
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_row_strategies_resolve_defaults_and_traffic_tiers():
    maintain = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=100,
        strategy_id="maintain",
        param=None,
        ed=1.0,
    )
    price_cut = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=100,
        strategy_id="price_cut",
        param=None,
        ed=1.0,
    )
    traffic = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=100,
        strategy_id="traffic_boost",
        param=None,
        ed=1.0,
        traffic_tier="aggressive",
    )

    assert maintain["sim_qty"] == 100.0
    assert maintain["sim_price"] == 100.0
    assert price_cut["sim_qty"] == 108.0
    assert price_cut["sim_price"] == 92.0
    assert traffic["sim_qty"] == 125.0
    assert traffic["param"] == "+25%"
    assert traffic["traffic_tier"] == "aggressive"


def test_optimize_filters_candidates_by_product_status():
    eol = whatif.search_optimize(
        baseline_qty=100,
        baseline_price=100,
        target_qty=120,
        ed=1.0,
        status="淘汰",
    )
    general = whatif.search_optimize(
        baseline_qty=100,
        baseline_price=100,
        target_qty=108,
        ed=1.0,
        status="主销",
    )
    new = whatif.search_optimize(
        baseline_qty=100,
        baseline_price=100,
        target_qty=112,
        ed=1.0,
        status="新品",
    )

    assert eol["strategy_id"] in {"maintain", "eol_clearance"}
    assert general["strategy_id"] == "price_cut"
    assert new["strategy_id"] in {"traffic_boost", "prelaunch"}


def test_optimize_can_consider_revenue_target_with_quantity_target():
    result = whatif.search_optimize(
        baseline_qty=100,
        baseline_price=100,
        target_qty=130,
        target_revenue=9936,
        ed=1.0,
        status="主销",
    )

    # trade_in exactly matches the quantity target, while price_cut exactly
    # matches the revenue target; the normalized combined score selects the
    # latter instead of silently optimizing quantity only.
    assert result["strategy_id"] == "price_cut"
    assert result["sim_amount"] == 9936.0
    assert result["amount_gap"] == 0.0


def test_one_sku_strategy_applies_to_all_month_channel_details():
    details = [
        {
            "sku": "A",
            "month": "2026-09",
            "forecast_qty": 100,
            "baseline_price": 100,
            "cost_price": 60,
        },
        {
            "sku": "A",
            "month": "2026-10",
            "forecast_qty": 50,
            "baseline_price": 200,
            "cost_price": 120,
        },
    ]
    result = whatif.simulate_row(
        baseline_qty=150,
        baseline_price=133.333333,
        strategy_id="price_cut",
        param="-10%",
        ed=1.0,
        details=details,
    )

    assert result["sim_qty"] == 165.0
    assert result["sim_amount"] == 19800.0
    assert result["sim_price"] == 120.0
    assert result["sim_gross_profit"] == 6600.0
    assert [item["sim_qty"] for item in result["details"]] == [110.0, 55.0]


def test_historical_detail_price_drives_maintain_price_cut_and_bundle():
    details = [
        {
            "sku": "HIST-A",
            "month": "2026-09",
            "forecast_qty": 100,
            "baseline_price": 100,
            "cost_price": 60,
        },
    ]

    maintain = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=999,
        strategy_id="maintain",
        param=None,
        ed=1.0,
        details=details,
    )
    price_cut = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=999,
        strategy_id="price_cut",
        param="-10%",
        ed=1.0,
        details=details,
    )
    bundle = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=999,
        strategy_id="bundle",
        param=None,
        ed=1.0,
        details=details,
    )

    assert maintain["sim_price"] == 100.0
    assert maintain["sim_amount"] == 10000.0
    assert price_cut["sim_price"] == 90.0
    assert price_cut["sim_qty"] == 110.0
    assert price_cut["sim_amount"] == 9900.0
    assert bundle["sim_price"] == 115.0
    assert bundle["sim_qty"] == 110.0
    assert bundle["sim_amount"] == 12650.0
    assert maintain["price_status"] == "complete"


def test_detail_null_price_falls_back_to_row_baseline_price():
    result = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=100,
        strategy_id="maintain",
        param=None,
        ed=1.0,
        details=[
            {
                "sku": "FALLBACK-A",
                "month": "2026-09",
                "forecast_qty": 100,
                "baseline_price": None,
            },
        ],
    )

    assert result["sim_price"] == 100.0
    assert result["sim_amount"] == 10000.0
    assert result["price_status"] == "complete"
    assert result["details"][0]["sim_price"] == 100.0


def test_missing_price_keeps_amount_null_and_optimize_falls_back_to_quantity():
    simulated = whatif.simulate_row(
        baseline_qty=100,
        baseline_price=None,
        strategy_id="maintain",
        param=None,
        ed=1.0,
    )
    optimized = whatif.search_optimize(
        baseline_qty=100,
        baseline_price=None,
        target_qty=100,
        target_revenue=10000,
        ed=1.0,
        status="主销",
    )

    assert simulated["sim_qty"] == 100.0
    assert simulated["sim_price"] is None
    assert simulated["sim_amount"] is None
    assert simulated["sim_gross_profit"] is None
    assert simulated["price_status"] == "missing"
    assert optimized["strategy_id"] == "maintain"
    assert optimized["sim_amount"] is None
    assert optimized["amount_gap"] is None


def test_model_requests_reject_empty_rows():
    simulate_request, optimize_request = _load_server_request_models()

    with pytest.raises(ValidationError):
        simulate_request(strategy_id="maintain", rows=[])
    with pytest.raises(ValidationError):
        optimize_request(target_qty=10, rows=[])


def test_model_rows_accept_null_channel_for_multi_channel_sku():
    simulate_request, optimize_request = _load_server_request_models()
    row = {
        "sku": "MULTI-CHANNEL-A",
        "channel_l3": None,
        "category": "冰箱",
        "baseline_qty": 100,
        "details": [{"sku": "MULTI-CHANNEL-A", "forecast_qty": 100}],
    }

    simulated = simulate_request(strategy_id="maintain", rows=[row])
    optimized = optimize_request(target_qty=100, rows=[row])

    assert simulated.rows[0].channel_l3 is None
    assert optimized.rows[0].channel_l3 is None
