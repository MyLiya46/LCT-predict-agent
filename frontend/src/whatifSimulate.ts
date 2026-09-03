/** What-if 前端演算（与后端策略目录同源约定）。 */

export type TrafficTierId = "conservative" | "medium" | "aggressive";

export type WhatIfStrategyMeta = {
  id: string;
  name: string;
  statuses: string[];
  param_label: string | null;
  default_param: string;
  param_kind: string;
  qty_effect: string;
  price_effect: string;
  summary: string;
  tiers?: { id: string; label: string; param: string; lift: number }[];
  default_tier?: string;
};

export type ElasticityInfo = {
  coefficient: number | null;
  volatility_class: string;
  elasticity_class: string;
  ed: number;
  ed_source: string;
};

export const TRAFFIC_TIERS: {
  id: TrafficTierId;
  label: string;
  param: string;
  lift: number;
}[] = [
  { id: "conservative", label: "保守", param: "+5%", lift: 0.05 },
  { id: "medium", label: "中等", param: "+12%", lift: 0.12 },
  { id: "aggressive", label: "强推", param: "+25%", lift: 0.25 },
];

export const DEFAULT_TRAFFIC_TIER: TrafficTierId = "medium";

export function parseParamPct(raw: string): number | null {
  const m = String(raw || "").replace(/\s/g, "").match(/-?\d+(\.\d+)?/);
  if (!m) return null;
  return Number(m[0]) / 100;
}

export function formatPctParam(pct: number): string {
  const v = pct * 100;
  const sign = v > 0 ? "+" : "";
  const text = Number.isInteger(v) ? String(v) : v.toFixed(1);
  return `${sign}${text}%`;
}

export function strategiesForStatusGroup(
  catalog: WhatIfStrategyMeta[],
  status: string,
): WhatIfStrategyMeta[] {
  const group =
    status === "淘汰" ? "eol" : status === "新品" ? "new" : "general";
  return catalog.filter((s) => s.statuses.includes(group));
}

export function defaultStrategyId(status: string): string {
  if (status === "淘汰") return "maintain";
  if (status === "新品") return "plan_launch";
  return "maintain";
}

export function simulateRow(input: {
  baseline_qty: number;
  plan_price: number | null;
  strategy_id: string;
  param: string;
  ed: number;
  traffic_tier?: TrafficTierId | null;
}): { sim_qty: number; sim_price: number } {
  const {
    baseline_qty: baseline,
    plan_price,
    strategy_id: sid,
    param,
    ed,
  } = input;
  const basePrice = plan_price ?? 0;

  let sim_price = basePrice;
  let sim_qty = baseline;

  if (sid === "price_cut") {
    let pct = parseParamPct(param) ?? -0.08;
    if (pct > 0) pct = -Math.abs(pct);
    sim_price = basePrice * (1 + pct);
    const lift = Math.min(0.8, Math.max(0, ed * Math.abs(pct)));
    sim_qty = baseline * (1 + lift);
  } else if (sid === "eol_clearance") {
    let pct = parseParamPct(param) ?? -0.3;
    if (pct > 0) pct = -Math.abs(pct);
    sim_price = basePrice * (1 + pct);
    sim_qty = baseline * 0.65;
  } else if (sid === "traffic_boost") {
    const tier =
      TRAFFIC_TIERS.find((t) => t.id === input.traffic_tier) ||
      TRAFFIC_TIERS.find((t) => t.id === DEFAULT_TRAFFIC_TIER)!;
    const lift = parseParamPct(param) ?? tier.lift;
    sim_qty = baseline * (1 + Math.max(0, lift));
  } else if (sid === "trade_in") {
    const lift = parseParamPct(param) ?? 0.3;
    sim_qty = baseline * (1 + Math.max(0, lift));
  } else if (sid === "gift") {
    const lift = parseParamPct(param) ?? 0.06;
    sim_qty = baseline * (1 + Math.max(0, lift));
  } else if (sid === "bundle") {
    const atv = parseParamPct(param) ?? 0.15;
    sim_price = basePrice * (1 + Math.max(0, atv));
    sim_qty = baseline * 1.1;
  } else if (sid === "prelaunch") {
    sim_qty = baseline * 1.12;
  }
  // maintain / plan_launch: unchanged

  return {
    sim_qty: Math.round(sim_qty * 10) / 10,
    sim_price: Math.round(sim_price * 100) / 100,
  };
}

export function suggestPriceCutParam(ed: number, needLift: number): string {
  // needLift = 目标相对基线的销量缺口比例；ΔP = -needLift / Ed
  if (ed <= 0) return "-8%";
  const pct = Math.min(0.25, Math.max(0.03, needLift / ed));
  return formatPctParam(-pct);
}
