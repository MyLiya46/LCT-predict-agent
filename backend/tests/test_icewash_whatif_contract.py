from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_row_strategies_resolve_defaults_and_traffic_tiers():
    maintain = whatif.simulate_row(
        baseline_qty=100,
        plan_price=100,
        strategy_id="maintain",
        param=None,
        ed=1.0,
    )
    price_cut = whatif.simulate_row(
        baseline_qty=100,
        plan_price=100,
        strategy_id="price_cut",
        param=None,
        ed=1.0,
    )
    traffic = whatif.simulate_row(
        baseline_qty=100,
        plan_price=100,
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
        plan_price=100,
        target_qty=120,
        ed=1.0,
        status="淘汰",
    )
    general = whatif.search_optimize(
        baseline_qty=100,
        plan_price=100,
        target_qty=108,
        ed=1.0,
        status="主销",
    )
    new = whatif.search_optimize(
        baseline_qty=100,
        plan_price=100,
        target_qty=112,
        ed=1.0,
        status="新品",
    )

    assert eol["strategy_id"] in {"maintain", "eol_clearance"}
    assert general["strategy_id"] == "price_cut"
    assert new["strategy_id"] in {"traffic_boost", "prelaunch"}
