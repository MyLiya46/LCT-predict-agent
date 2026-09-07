# -*- coding: utf-8 -*-
"""What-If 规则式策略引擎（feat-icewash §3.4/§3.5/§6）。

simulate/optimize 的策略目录与演算公式的「单一事实来源」：
backend 仅 taskid 转发，前端工作台下拉与 LLM 解析均从 `/whatif/strategies` 读取，不各维护一份。

- STRATEGY_CATALOG：8 条策略（feat-icewash §3.4 命名）+ 经验提升/价格弹性公式 + 适用 status 分组。
- simulate_row：单 SKU 演算（对齐 ref whatifSimulate.ts simulateRow 语义，重新落到 icewash）。
- optimize_row / search_optimize：给定目标销量（可选销售额）→ 候选取最小归一化目标差距（§3.5，按 statuses 过滤）。

纯计算层：只依赖 numpy（不依赖 lightgbm / pandas / PG / MySQL）。baseline 由调用方（server 端点 /
backend 工具）传入 per-SKU 行，本模块不读取预测产物。
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Dict, List, Optional

# 加大投流二级档位（align ref）
TRAFFIC_TIERS: List[Dict[str, Any]] = [
    {"id": "conservative", "label": "保守", "param": "+5%", "lift": 0.05},
    {"id": "medium", "label": "中等", "param": "+12%", "lift": 0.12},
    {"id": "aggressive", "label": "强推", "param": "+25%", "lift": 0.25},
]
DEFAULT_TRAFFIC_TIER = "medium"

# statuses_group: eol | new | general（align ref + 源方案 §3.4 8 策略）
STRATEGY_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "maintain",
        "name": "维持现状",
        "statuses": ["eol", "new", "general"],
        "param_label": None,
        "default_param": "",
        "param_kind": "none",
        "qty_effect": "不变",
        "price_effect": "不变",
        "summary": "价量均保持基线预测",
    },
    {
        "id": "price_cut",
        "name": "降价促销",
        "statuses": ["general"],
        "param_label": "价格变动%",
        "default_param": "-8%",
        "param_kind": "price_pct",
        "qty_effect": "%ΔQty = Ed × |ΔP|（上限 80%）",
        "price_effect": "基线价 × (1+ΔP)",
        "summary": "按型号价格弹性系数 Ed 调量；默认降价 8%",
    },
    {
        "id": "traffic_boost",
        "name": "加大投流",
        "statuses": ["new", "general"],
        "param_label": "销量增量%",
        "default_param": "+12%",
        "param_kind": "traffic_tier",
        "qty_effect": "基线 × (1+增量%)",
        "price_effect": "不变",
        "summary": "二级档位：保守 +5% / 中等 +12% / 强推 +25%；可手改参数",
        "tiers": TRAFFIC_TIERS,
        "default_tier": DEFAULT_TRAFFIC_TIER,
    },
    {
        "id": "trade_in",
        "name": "以旧换新",
        "statuses": ["general"],
        "param_label": "销量提升%",
        "default_param": "+30%",
        "param_kind": "lift_pct",
        "qty_effect": "基线 × (1+提升%)",
        "price_effect": "不变",
        "summary": "知识库通用 CVR +25%~+35%，默认 +30%",
    },
    {
        "id": "gift",
        "name": "赠品促销",
        "statuses": ["new", "general"],
        "param_label": "销量增量%",
        "default_param": "+6%",
        "param_kind": "lift_pct",
        "qty_effect": "基线 × (1+增量%)",
        "price_effect": "不变",
        "summary": "CVR +5%~+8% 中位，默认 +6%",
    },
    {
        "id": "bundle",
        "name": "套购",
        "statuses": ["general"],
        "param_label": "ATV 溢价%",
        "default_param": "+15%",
        "param_kind": "atv_pct",
        "qty_effect": "基线 × 1.10",
        "price_effect": "基线价 × (1+ATV%)",
        "summary": "量 +10%；有效客单按 ATV 溢价提升（默认 +15%）",
    },
    {
        "id": "prelaunch",
        "name": "提前铺货",
        "statuses": ["new"],
        "param_label": None,
        "default_param": "",
        "param_kind": "none",
        "qty_effect": "基线 × 1.12",
        "price_effect": "不变",
        "summary": "新品抢档期，销量 +12%",
    },
    {
        "id": "eol_clearance",
        "name": "清仓退市",
        "statuses": ["eol"],
        "param_label": "清仓折扣%",
        "default_param": "-30%",
        "param_kind": "price_pct",
        "qty_effect": "基线 × 0.65",
        "price_effect": "基线价 × (1+折扣%)",
        "summary": "尾货清理：量 -35%，默认价 -30%",
    },
]

STATUS_GROUP_LABELS = {
    "eol": "淘汰",
    "new": "新品",
    "general": "主销/其他",
}

PRICE_CUT_CAP = 0.8  # 降价促销提量上限（对齐 ref：min(0.8, Ed×|ΔP|)）


def _coerce_price(value: Any) -> Optional[float]:
    """Return a finite, non-negative price while preserving explicit zero."""
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed) or parsed < 0:
        return None
    return parsed


def resolve_detail_price(
    detail: Dict[str, Any], row_baseline_price: Optional[float]
) -> Optional[float]:
    """Resolve the effective baseline price for one forecast detail.

    The backend has already resolved the planned price or historical fallback;
    the model must not infer a different price source during simulation.
    """
    resolved = _coerce_price(detail.get("baseline_price"))
    return resolved if resolved is not None else _coerce_price(row_baseline_price)


def _strategy_definition(strategy_id: str) -> Optional[Dict[str, Any]]:
    return next((strategy for strategy in STRATEGY_CATALOG if strategy["id"] == strategy_id), None)


def effective_strategy_param(strategy_id: str, param: Optional[str]) -> str:
    """Resolve the parameter actually used by a strategy calculation."""
    strategy = _strategy_definition(strategy_id)
    if strategy is None:
        return str(param or "").strip()
    if strategy["param_kind"] == "none":
        return ""
    value = str(param or "").strip()
    if strategy_id == "traffic_boost" and not value:
        # A selected traffic tier is itself the parameter source.  Do not
        # replace an aggressive/conservative tier with the catalog's medium
        # default merely because the caller omitted the text representation.
        return ""
    return value or str(strategy.get("default_param") or "")


def effective_traffic_tier(strategy_id: str, traffic_tier: Optional[str]) -> Optional[str]:
    if strategy_id != "traffic_boost":
        return traffic_tier
    valid_ids = {str(item["id"]) for item in TRAFFIC_TIERS}
    return traffic_tier if traffic_tier in valid_ids else DEFAULT_TRAFFIC_TIER


def parse_param_pct(raw: Optional[str]) -> Optional[float]:
    """解析参数百分比字符串为小数（'+12%' → 0.12，'-8%' → -0.08）。"""
    if raw is None:
        return None
    m = str(raw).replace(" ", "").strip()
    import re

    m = re.match(r"^([+-]?\d+(?:\.\d+)?)%?$", m)
    if not m:
        return None
    return float(m.group(1)) / 100.0


def status_group(status: Optional[str]) -> str:
    s = (status or "").strip()
    if s == "淘汰":
        return "eol"
    if s == "新品":
        return "new"
    return "general"


def resolve_ed(elasticity_coef: Optional[float], elasticity_class: Optional[str]) -> float:
    """返回弹性系数 Ed（优先读取价格弹性表；缺省时按类别 fallback）。"""
    if elasticity_coef is not None and elasticity_coef > 0:
        return float(elasticity_coef)
    cls = (elasticity_class or "").strip()
    if "价格敏感" in cls or cls == "强敏感":
        return 1.5
    if "弱敏感" in cls:
        return 0.8
    if "不敏感" in cls or "钝感" in cls:
        return 0.6
    return 1.0


def list_strategies(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回策略目录；传 status 时按适用状态过滤。"""
    if status is None or status == "":
        return [dict(s) for s in STRATEGY_CATALOG]
    group = status_group(status)
    return [dict(s) for s in STRATEGY_CATALOG if group in s["statuses"]]


def strategies_response(status: Optional[str] = None) -> Dict[str, Any]:
    items = list_strategies(status=status)
    return {
        "ok": True,
        "status": status,
        "status_group": status_group(status) if status else None,
        "status_group_labels": STATUS_GROUP_LABELS,
        "traffic_tiers": TRAFFIC_TIERS,
        "default_traffic_tier": DEFAULT_TRAFFIC_TIER,
        "strategies": items,
        "total": len(items),
    }


def simulate_row(
    *,
    baseline_qty: float,
    baseline_price: Optional[float],
    strategy_id: str,
    param: Optional[str],
    ed: float,
    traffic_tier: Optional[str] = None,
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """单 SKU 演算（对齐 ref simulateRow 语义）。

    ``details`` 存在时，所有月份/渠道明细使用同一个策略，再汇总为一个
    型号结果；没有明细时保留原来的单行计算兼容路径。
    """
    if details:
        return _simulate_details(
            baseline_qty=baseline_qty,
            baseline_price=baseline_price,
            strategy_id=strategy_id,
            param=param,
            ed=ed,
            traffic_tier=traffic_tier,
            details=details,
        )

    base_qty = float(baseline_qty or 0.0)
    base_price = _coerce_price(baseline_price)
    sim_price = base_price
    sim_qty = base_qty
    effect_note = "不变"

    sid = strategy_id
    used_param = effective_strategy_param(sid, param)
    used_tier = effective_traffic_tier(sid, traffic_tier)

    if sid == "price_cut":
        pct = parse_param_pct(used_param) or -0.08
        if pct > 0:
            pct = -abs(pct)
        sim_price = base_price * (1 + pct) if base_price is not None else None
        lift = min(PRICE_CUT_CAP, max(0.0, ed * abs(pct)))
        sim_qty = base_qty * (1 + lift)
        effect_note = f"降价 {pct*100:.1f}% · Ed={ed:.2f} · 量 +{lift*100:.1f}%"
    elif sid == "eol_clearance":
        pct = parse_param_pct(used_param) or -0.30
        if pct > 0:
            pct = -abs(pct)
        sim_price = base_price * (1 + pct) if base_price is not None else None
        sim_qty = base_qty * 0.65
        effect_note = f"清仓折扣 {pct*100:.1f}% · 量 -35%"
    elif sid == "traffic_boost":
        tier = next((t for t in TRAFFIC_TIERS if t["id"] == used_tier), None)
        if tier is None:
            tier = next(t for t in TRAFFIC_TIERS if t["id"] == DEFAULT_TRAFFIC_TIER)
        if not used_param:
            used_param = str(tier["param"])
        lift = parse_param_pct(used_param) if parse_param_pct(used_param) is not None else tier["lift"]
        sim_qty = base_qty * (1 + max(0.0, lift))
        effect_note = f"投流档位 {tier['label']} · 量 +{lift*100:.1f}%"
    elif sid == "trade_in":
        lift = parse_param_pct(used_param) if parse_param_pct(used_param) is not None else 0.30
        sim_qty = base_qty * (1 + max(0.0, lift))
        effect_note = f"以旧换新 · 量 +{lift*100:.1f}%"
    elif sid == "gift":
        lift = parse_param_pct(used_param) if parse_param_pct(used_param) is not None else 0.06
        sim_qty = base_qty * (1 + max(0.0, lift))
        effect_note = f"赠品促销 · 量 +{lift*100:.1f}%"
    elif sid == "bundle":
        atv = parse_param_pct(used_param) if parse_param_pct(used_param) is not None else 0.15
        sim_price = base_price * (1 + max(0.0, atv)) if base_price is not None else None
        sim_qty = base_qty * 1.10
        effect_note = f"套购 · 量 +10% · 客单 +{atv*100:.1f}%"
    elif sid == "prelaunch":
        sim_qty = base_qty * 1.12
        effect_note = "提前铺货 · 量 +12%"
    # maintain 及未知策略：不变

    sim_amount = float(sim_qty) * sim_price if sim_price is not None else None
    price_coverage = 1.0 if base_price is not None else 0.0
    return {
        "sim_qty": round(float(sim_qty), 2),
        "sim_price": round(float(sim_price), 2) if sim_price is not None else None,
        "sim_amount": round(sim_amount, 2) if sim_amount is not None else None,
        "sim_gross_profit": None,
        "effect_note": effect_note,
        "param": used_param or None,
        "traffic_tier": used_tier,
        "price_coverage_qty": price_coverage,
        "price_status": "complete" if base_price is not None else "missing",
        "cost_coverage_qty": 0.0,
        "cost_status": "missing",
        "gross_coverage_qty": 0.0,
        "gross_profit_status": "missing",
    }


def _simulate_details(
    *,
    baseline_qty: float,
    baseline_price: Optional[float],
    strategy_id: str,
    param: Optional[str],
    ed: float,
    traffic_tier: Optional[str],
    details: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply one strategy to each forecast detail and aggregate the result."""
    simulated_details: List[Dict[str, Any]] = []
    total_qty = 0.0
    total_baseline_qty = 0.0
    total_amount = 0.0
    total_gross_profit = 0.0
    priced_qty = 0.0
    cost_qty = 0.0
    gross_qty = 0.0
    resolved_price_flags: List[bool] = []
    first_effect: Optional[str] = None

    for detail in details:
        raw_qty = detail.get("forecast_qty", detail.get("baseline_qty", 0.0))
        try:
            detail_qty = float(raw_qty or 0.0)
        except (TypeError, ValueError):
            detail_qty = 0.0
        detail_price = resolve_detail_price(detail, baseline_price)
        resolved_price_flags.append(detail_price is not None)
        detail_coef = detail.get("elasticity_coef")
        detail_class = detail.get("elasticity_class")
        nested_elasticity = detail.get("elasticity")
        if isinstance(nested_elasticity, dict):
            if detail_coef in (None, ""):
                detail_coef = nested_elasticity.get("coefficient")
            if detail_class in (None, ""):
                detail_class = nested_elasticity.get("elasticity_class")
        try:
            parsed_coef = float(detail_coef) if detail_coef not in (None, "") else None
        except (TypeError, ValueError):
            parsed_coef = None
        detail_ed = (
            resolve_ed(parsed_coef, str(detail_class) if detail_class not in (None, "") else None)
            if parsed_coef is not None or detail_class not in (None, "")
            else ed
        )
        result = simulate_row(
            baseline_qty=detail_qty,
            baseline_price=detail_price,
            strategy_id=strategy_id,
            param=param,
            ed=detail_ed,
            traffic_tier=traffic_tier,
        )
        sim_qty = float(result["sim_qty"])
        sim_price = result.get("sim_price")
        sim_price_value = float(sim_price) if sim_price is not None else None
        sim_amount = sim_qty * sim_price_value if sim_price_value is not None else None
        if detail_price is not None:
            priced_qty += detail_qty
            if sim_amount is not None:
                total_amount += sim_amount
        raw_cost = detail.get("cost_price")
        try:
            cost = float(raw_cost) if raw_cost not in (None, "") else None
        except (TypeError, ValueError):
            cost = None
        if cost is not None:
            cost_qty += detail_qty
        sim_gross_profit = (
            (sim_price_value - cost) * sim_qty
            if cost is not None and sim_price_value is not None
            else None
        )
        if sim_gross_profit is not None:
            total_gross_profit += sim_gross_profit
            gross_qty += detail_qty
        total_baseline_qty += detail_qty
        total_qty += sim_qty
        first_effect = first_effect or str(result.get("effect_note") or "不变")
        simulated_details.append({
            **detail,
            "sim_qty": round(sim_qty, 2),
            "sim_price": round(sim_price_value, 2) if sim_price_value is not None else None,
            "sim_amount": round(sim_amount, 2) if sim_amount is not None else None,
            "sim_gross_profit": round(sim_gross_profit, 2) if sim_gross_profit is not None else None,
            "price_status": "matched" if detail_price is not None else "missing",
        })

    price_coverage = priced_qty / total_baseline_qty if total_baseline_qty > 0 else 0.0
    cost_coverage = cost_qty / total_baseline_qty if total_baseline_qty > 0 else 0.0
    gross_coverage = gross_qty / total_baseline_qty if total_baseline_qty > 0 else 0.0
    price_complete = (
        price_coverage >= 1.0
        if total_baseline_qty > 0
        else bool(resolved_price_flags) and all(resolved_price_flags)
    )
    aggregate_price = total_amount / total_qty if price_complete and total_qty > 0 else None
    aggregate_amount = total_amount if price_complete else None
    aggregate_gross_profit = (
        total_gross_profit if price_complete and gross_qty > 0 else None
    )
    # Keep the legacy scalar result shape while exposing the detail-level
    # values needed by the SKU matrix and monthly trend chart.
    return {
        "sim_qty": round(total_qty, 2),
        "sim_price": round(aggregate_price, 2) if aggregate_price is not None else None,
        "sim_amount": round(aggregate_amount, 2) if aggregate_amount is not None else None,
        "sim_gross_profit": round(aggregate_gross_profit, 2)
        if aggregate_gross_profit is not None
        else None,
        "effect_note": f"{first_effect or '不变'} · 已应用 {len(simulated_details)} 条明细",
        "param": effective_strategy_param(strategy_id, param) or None,
        "traffic_tier": effective_traffic_tier(strategy_id, traffic_tier),
        "price_coverage_qty": round(price_coverage, 6),
        "price_status": "complete" if price_coverage >= 1 else "partial" if price_coverage > 0 else "missing",
        "cost_coverage_qty": round(cost_coverage, 6),
        "cost_status": "complete" if cost_coverage >= 1 else "partial" if cost_coverage > 0 else "missing",
        "gross_coverage_qty": round(gross_coverage, 6),
        "gross_profit_status": "complete" if gross_coverage >= 1 else "partial" if gross_coverage > 0 else "missing",
        "details": simulated_details,
    }


def optimize_row(
    *,
    baseline_qty: float,
    baseline_price: Optional[float],
    target_qty: float,
    ed: float,
    target_revenue: Optional[float] = None,
    candidate_ids: Optional[List[str]] = None,
    param: Optional[str] = None,
    traffic_tier: Optional[str] = None,
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """单 SKU optimize：候选中逐条 simulate，按销量/销售额目标选择最优策略。

    没有传入销售额目标时保留原来的销量目标逻辑。两个目标同时存在时，
    使用各自相对目标的归一化差距相加，避免销量和金额的量纲直接相加。
    """
    candidates = [s for s in STRATEGY_CATALOG if candidate_ids is None or s["id"] in candidate_ids]
    best = None
    best_score = float("inf")
    for strat in candidates:
        res = simulate_row(
            baseline_qty=baseline_qty,
            baseline_price=baseline_price,
            strategy_id=strat["id"],
            param=param if strat["param_kind"] != "none" else "",
            ed=ed,
            traffic_tier=traffic_tier,
            details=details,
        )
        qty_gap = abs(res["sim_qty"] - float(target_qty))
        raw_sim_amount = res.get("sim_amount")
        sim_amount = float(raw_sim_amount) if raw_sim_amount is not None else None
        amount_gap = None
        if target_revenue is None or sim_amount is None:
            score = qty_gap
        else:
            amount_gap = abs(sim_amount - float(target_revenue))
            qty_scale = max(abs(float(target_qty)), 1.0)
            amount_scale = max(abs(float(target_revenue)), 1.0)
            score = qty_gap / qty_scale + amount_gap / amount_scale
        if score < best_score:
            best_score = score
            best = {
                "strategy_id": strat["id"],
                "strategy_name": strat["name"],
                **res,
                "sim_amount": round(sim_amount, 2) if sim_amount is not None else None,
                "gap": round(qty_gap, 2),
                "amount_gap": round(amount_gap, 2) if amount_gap is not None else None,
                "score": round(score, 6),
            }
    return best or {}


def search_optimize(
    *,
    baseline_qty: float,
    baseline_price: Optional[float],
    target_qty: float,
    ed: float,
    target_revenue: Optional[float] = None,
    status: Optional[str] = None,
    param: Optional[str] = None,
    traffic_tier: Optional[str] = None,
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """优化搜索入口：候选空间 = STRATEGY_CATALOG（按 statuses 过滤，§3.5）。"""
    if status is None or status == "":
        candidate_ids = None
    else:
        candidate_ids = [s["id"] for s in list_strategies(status=status)]
    return optimize_row(
        baseline_qty=baseline_qty,
        baseline_price=baseline_price,
        target_qty=target_qty,
        target_revenue=target_revenue,
        ed=ed,
        candidate_ids=candidate_ids,
        param=param,
        traffic_tier=traffic_tier,
        details=details,
    )
