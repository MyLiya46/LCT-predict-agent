# -*- coding: utf-8 -*-
"""What-If 规则式策略引擎（feat-icewash §3.4/§3.5/§6）。

simulate/optimize 的策略目录与演算公式的「单一事实来源」：
backend 仅 taskid 转发，前端工作台下拉与 LLM 解析均从 `/whatif/strategies` 读取，不各维护一份。

- STRATEGY_CATALOG：8 条策略（feat-icewash §3.4 命名）+ 经验提升/价格弹性公式 + 适用 status 分组。
- simulate_row：单 SKU 演算（对齐 ref whatifSimulate.ts simulateRow 语义，重新落到 icewash）。
- optimize_row / search_optimize：给定目标销量 → 候选取 argmin|销量-目标|（§3.5，按 statuses 过滤）。

纯计算层：只依赖 numpy（不依赖 lightgbm / pandas / PG / MySQL）。baseline 由调用方（server 端点 /
backend 工具）传入 per-SKU 行，本模块不读取预测产物。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

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
        "price_effect": "计划价 × (1+ΔP)",
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
        "price_effect": "计划价 × (1+ATV%)",
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
        "price_effect": "计划价 × (1+折扣%)",
        "summary": "尾货清理：量 -35%，默认价 -30%",
    },
]

STATUS_GROUP_LABELS = {
    "eol": "淘汰",
    "new": "新品",
    "general": "主销/其他",
}

PRICE_CUT_CAP = 0.8  # 降价促销提量上限（对齐 ref：min(0.8, Ed×|ΔP|)）


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
    """返回弹性系数 Ed（就近读 icewash 产物里的 plan_price 弹性；缺省时按类别 fallback）。"""
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
    plan_price: Optional[float],
    strategy_id: str,
    param: Optional[str],
    ed: float,
    traffic_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """单 SKU 演算（对齐 ref simulateRow 语义）。返回 {sim_qty, sim_price, effect_note}。"""
    base_qty = float(baseline_qty or 0.0)
    base_price = float(plan_price or 0.0)
    sim_price = base_price
    sim_qty = base_qty
    effect_note = "不变"

    sid = strategy_id

    if sid == "price_cut":
        pct = parse_param_pct(param) or -0.08
        if pct > 0:
            pct = -abs(pct)
        sim_price = base_price * (1 + pct)
        lift = min(PRICE_CUT_CAP, max(0.0, ed * abs(pct)))
        sim_qty = base_qty * (1 + lift)
        effect_note = f"降价 {pct*100:.1f}% · Ed={ed:.2f} · 量 +{lift*100:.1f}%"
    elif sid == "eol_clearance":
        pct = parse_param_pct(param) or -0.30
        if pct > 0:
            pct = -abs(pct)
        sim_price = base_price * (1 + pct)
        sim_qty = base_qty * 0.65
        effect_note = f"清仓折扣 {pct*100:.1f}% · 量 -35%"
    elif sid == "traffic_boost":
        tier = next((t for t in TRAFFIC_TIERS if t["id"] == traffic_tier), None)
        if tier is None:
            tier = next(t for t in TRAFFIC_TIERS if t["id"] == DEFAULT_TRAFFIC_TIER)
        lift = parse_param_pct(param) if parse_param_pct(param) is not None else tier["lift"]
        sim_qty = base_qty * (1 + max(0.0, lift))
        effect_note = f"投流档位 {tier['label']} · 量 +{lift*100:.1f}%"
    elif sid == "trade_in":
        lift = parse_param_pct(param) if parse_param_pct(param) is not None else 0.30
        sim_qty = base_qty * (1 + max(0.0, lift))
        effect_note = f"以旧换新 · 量 +{lift*100:.1f}%"
    elif sid == "gift":
        lift = parse_param_pct(param) if parse_param_pct(param) is not None else 0.06
        sim_qty = base_qty * (1 + max(0.0, lift))
        effect_note = f"赠品促销 · 量 +{lift*100:.1f}%"
    elif sid == "bundle":
        atv = parse_param_pct(param) if parse_param_pct(param) is not None else 0.15
        sim_price = base_price * (1 + max(0.0, atv))
        sim_qty = base_qty * 1.10
        effect_note = f"套购 · 量 +10% · 客单 +{atv*100:.1f}%"
    elif sid == "prelaunch":
        sim_qty = base_qty * 1.12
        effect_note = "提前铺货 · 量 +12%"
    # maintain 及未知策略：不变

    return {"sim_qty": round(float(sim_qty), 2), "sim_price": round(float(sim_price), 2), "effect_note": effect_note}


def optimize_row(
    *,
    baseline_qty: float,
    plan_price: Optional[float],
    target_qty: float,
    ed: float,
    candidate_ids: Optional[List[str]] = None,
    param: Optional[str] = None,
    traffic_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """单 SKU optimize：候选中逐条 simulate → argmin|销量-目标| → 最优策略 + 对应销量。"""
    candidates = [s for s in STRATEGY_CATALOG if candidate_ids is None or s["id"] in candidate_ids]
    best = None
    best_gap = float("inf")
    for strat in candidates:
        res = simulate_row(
            baseline_qty=baseline_qty,
            plan_price=plan_price,
            strategy_id=strat["id"],
            param=param if strat["param_kind"] != "none" else "",
            ed=ed,
            traffic_tier=traffic_tier,
        )
        gap = abs(res["sim_qty"] - float(target_qty))
        if gap < best_gap:
            best_gap = gap
            best = {"strategy_id": strat["id"], "strategy_name": strat["name"], **res, "gap": round(gap, 2)}
    return best or {}


def search_optimize(
    *,
    baseline_qty: float,
    plan_price: Optional[float],
    target_qty: float,
    ed: float,
    status: Optional[str] = None,
    param: Optional[str] = None,
    traffic_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """优化搜索入口：候选空间 = STRATEGY_CATALOG（按 statuses 过滤，§3.5）。"""
    if status is None or status == "":
        candidate_ids = None
    else:
        candidate_ids = [s["id"] for s in list_strategies(status=status)]
    return optimize_row(
        baseline_qty=baseline_qty,
        plan_price=plan_price,
        target_qty=target_qty,
        ed=ed,
        candidate_ids=candidate_ids,
        param=param,
        traffic_tier=traffic_tier,
    )