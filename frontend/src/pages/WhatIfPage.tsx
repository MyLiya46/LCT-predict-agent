import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { EChartsOption, LineSeriesOption } from "echarts";
import {
  ChartLine,
  CircleNotch,
  FileArrowDown,
  Info,
  MagicWand,
  PencilSimple,
  Play,
  Robot,
  Terminal,
  X,
} from "@phosphor-icons/react";
import {
  fetchAttributionOptions,
  fetchWhatIfBaseline,
  fetchWhatIfStrategies,
  fetchWhatIfTask,
  fetchWorkbenchTable,
  submitWhatIfOptimization,
  submitWhatIfSimulation,
  type WhatIfBaselineItem,
  type WhatIfModelResultRow,
  type WhatIfModelRow,
  type WhatIfStrategy,
} from "../api";
import {
  DEFAULT_TRAFFIC_TIER,
  TRAFFIC_TIERS,
  defaultStrategyId,
  strategiesForStatusGroup,
  type TrafficTierId,
  type WhatIfStrategyMeta,
} from "../whatifSimulate";

const RIGHT_PANEL_MIN = 280;
const LEFT_PANEL_MIN = 420;
const RIGHT_PANEL_DEFAULT = 380;
const DEFAULT_GOAL_VOL = "8";
const DEFAULT_GOAL_REV = "50";

function versionsForCategory(allVersions: string[], category: string): string[] {
  if (!category) return allVersions;
  const prefix = `AG_${category}_`;
  const filtered = allVersions.filter((v) => v.startsWith(prefix));
  return filtered.length ? filtered : allVersions;
}

function latestVersion(versions: string[]): string | undefined {
  let best: { v: string; ts: number } | null = null;
  for (const v of versions) {
    const m = v.match(/(\d{8})_(\d{6})$/);
    const ts = m ? Number(m[1]) * 1_000_000 + Number(m[2]) : 0;
    if (!best || ts > best.ts) best = { v, ts };
  }
  return best?.v ?? versions[0];
}

function statusTone(status: string): "yellow" | "green" | "gray" {
  if (status === "淘汰" || status === "衰退") return "yellow";
  if (status === "新品") return "green";
  return "gray";
}

function formatQty(q: number): string {
  if (Math.abs(q) >= 10000) return `${(q / 10000).toFixed(1)}万件`;
  return `${Math.round(q).toLocaleString()}件`;
}

function formatPrice(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "-";
  return `¥${Math.round(p).toLocaleString()}`;
}

function formatAmount(amt: number): string {
  if (!Number.isFinite(amt)) return "-";
  if (Math.abs(amt) >= 1e8) return `${(amt / 1e8).toFixed(2)}亿`;
  if (Math.abs(amt) >= 1e4) return `${(amt / 1e4).toFixed(1)}万`;
  return `¥${Math.round(amt).toLocaleString()}`;
}

async function loadCostMap(category: string): Promise<Record<string, number>> {
  const map: Record<string, number> = {};
  let page = 1;
  const pageSize = 200;
  while (page <= 5) {
    const res = await fetchWorkbenchTable("cost_data", {
      category,
      page,
      page_size: pageSize,
    });
    for (const row of res.rows || []) {
      const sku = String(row["型号"] || "").trim();
      const cost = Number(row["成本价"]);
      if (sku && Number.isFinite(cost)) map[sku] = cost;
    }
    if (!res.rows?.length || (res.page ?? page) * pageSize >= (res.total ?? 0)) break;
    page += 1;
  }
  return map;
}

function formatMonthLabel(period: string): string {
  const m = period.match(/(\d{4})-(\d{2})/);
  if (!m) return period;
  return `${Number(m[2])}月`;
}

type SimRow = WhatIfBaselineItem & {
  strategyOptions: WhatIfStrategyMeta[];
  strategy_id: string;
  sim_price: number | null;
  cost_price: number | null;
  traffic_tier: TrafficTierId | null;
};

function rowMetrics(r: SimRow) {
  const simPrice = r.sim_price ?? r.plan_price ?? 0;
  const qty = r.sim_qty || 0;
  const cost = r.cost_price ?? 0;
  const simAmount = simPrice * qty;
  const grossProfit = (simPrice - cost) * qty;
  return { simAmount, grossProfit };
}

function seriesFromRows(
  rows: SimRow[],
  months: string[],
  value: "baseline_qty" | "sim_qty",
  fallbackSeries: number[] = [],
) {
  if (!months.length) return [];
  const totals = new Map<string, number>();
  for (const row of rows) {
    const month = String(row.period || "");
    if (!month) continue;
    totals.set(month, (totals.get(month) || 0) + Number(row[value] || 0));
  }
  if (totals.size) return months.map((month) => Number(((totals.get(month) || 0) / 10000).toFixed(2)));
  const base = rows.reduce((sum, row) => sum + Number(row.baseline_qty || 0), 0);
  const current = rows.reduce((sum, row) => sum + Number(row[value] || 0), 0);
  const lift = base > 0 ? current / base : 1;
  return fallbackSeries.map((item) => Number((item * lift).toFixed(2)));
}

function toModelRow(row: SimRow, strategyId?: string, param?: string, tier?: TrafficTierId | null): WhatIfModelRow {
  return {
    sku: row.sku,
    channel_l3: row.channel_l3,
    category: row.category,
    status: row.status,
    baseline_qty: row.baseline_qty,
    plan_price: row.plan_price,
    elasticity_coef: row.elasticity?.coefficient ?? null,
    elasticity_class: row.elasticity?.elasticity_class ?? null,
    strategy_id: strategyId ?? row.strategy_id,
    param: param ?? null,
    traffic_tier: tier ?? null,
  };
}

async function pollWhatIfTask(
  taskId: string,
  onProgress: (message: string) => void,
) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const task = await fetchWhatIfTask(taskId);
    if (task.progress) onProgress(task.progress);
    if (task.status === "completed") return task.result?.rows || [];
    if (task.status === "failed") {
      throw new Error(task.error_message || "icewash What-if 任务失败");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  throw new Error("icewash What-if 任务超时");
}

type KpiState = {
  vol: string;
  rev: string;
  margin: string;
  turn: string;
  volDiff: string;
  revDiff: string;
  volGap: string;
  revGap: string;
  progress: string;
  progressLabel: string;
  success: boolean | null;
  baselineRevM: string;
  simSeries: number[];
};

function emptyKpi(simSeries: number[] = []): KpiState {
  return {
    vol: "--",
    rev: "--",
    margin: "--",
    turn: "45 天",
    volDiff: "- (基线)",
    revDiff: "- (基线)",
    volGap: "--",
    revGap: "--",
    progress: "0%",
    progressLabel: "--",
    success: null,
    baselineRevM: "--",
    simSeries,
  };
}

function computeKpi(
  rows: SimRow[],
  goalVol: string,
  goalRev: string,
  opts: {
    success: boolean | null;
    labelMode: "baseline" | "sim";
    simSeries: number[];
    baselineAmount: number;
  },
): KpiState {
  const vol = rows.reduce((s, r) => s + (r.sim_qty || 0), 0);
  const rev = rows.reduce(
    (s, r) => s + (r.sim_price ?? r.plan_price ?? 0) * (r.sim_qty || 0),
    0,
  );
  const profit = rows.reduce((s, r) => s + rowMetrics(r).grossProfit, 0);
  const volWan = vol / 10000;
  const revM = rev / 1e6;
  const marginPct = rev > 0 ? (profit / rev) * 100 : 0;
  const goalVolN = Number(goalVol) || 0;
  const goalRevN = Number(goalRev) || 0;
  const volGap = Math.max(0, goalVolN - volWan);
  const revGap = Math.max(0, goalRevN - revM);
  const progress = goalRevN > 0 ? (revM / goalRevN) * 100 : 0;
  const ok = progress >= 100 && volWan >= goalVolN;
  const success =
    opts.success !== null
      ? opts.success
      : opts.labelMode === "baseline"
        ? null
        : ok;

  return {
    vol: volWan.toFixed(1),
    rev: revM.toFixed(1),
    margin: `${marginPct.toFixed(1)}%`,
    turn: "45 天",
    volDiff:
      opts.labelMode === "baseline"
        ? "- (基线)"
        : ok
          ? "达标"
          : volGap < 0.5
            ? "略低于目标"
            : "未达标",
    revDiff:
      opts.labelMode === "baseline"
        ? "- (基线)"
        : ok
          ? "达标"
          : revGap < 1
            ? "略低于目标"
            : "未达标",
    volGap: volGap.toFixed(1),
    revGap: revGap.toFixed(1),
    progress: `${progress.toFixed(1)}%`,
    progressLabel: `${progress.toFixed(1)}% (${ok ? "已达标" : "未达标"})`,
    success,
    baselineRevM: (opts.baselineAmount / 1e6).toFixed(1),
    simSeries: opts.simSeries,
  };
}

export default function WhatIfPage() {
  const [goalVol, setGoalVol] = useState(DEFAULT_GOAL_VOL);
  const [goalRev, setGoalRev] = useState(DEFAULT_GOAL_REV);
  const [agentRunning, setAgentRunning] = useState(false);
  const [simRunning, setSimRunning] = useState(false);
  const [agentDoneFlash, setAgentDoneFlash] = useState(false);
  const [simDoneFlash, setSimDoneFlash] = useState(false);
  const [rows, setRows] = useState<SimRow[]>([]);
  const [aiRecs, setAiRecs] = useState<string[]>([]);
  const [strategyIds, setStrategyIds] = useState<string[]>([]);
  const [params, setParams] = useState<string[]>([]);
  const [trafficTiers, setTrafficTiers] = useState<(TrafficTierId | null)[]>([]);
  const [strategyCatalog, setStrategyCatalog] = useState<WhatIfStrategy[]>([]);
  const [logs, setLogs] = useState<string[]>([
    "> 系统待命。等待选择基础预测或设定目标...",
  ]);
  const [kpi, setKpi] = useState<KpiState>(emptyKpi());
  const [chartMonths, setChartMonths] = useState<string[]>([]);
  const [baselineSeries, setBaselineSeries] = useState<number[]>([]);
  const [baselineAmount, setBaselineAmount] = useState(0);
  const [baselinePeriod, setBaselinePeriod] = useState("");
  const [loadingBaseline, setLoadingBaseline] = useState(false);
  const [simulationReady, setSimulationReady] = useState(false);
  const [agentReady, setAgentReady] = useState(false);

  const [categories, setCategories] = useState<string[]>([]);
  const [allVersions, setAllVersions] = useState<string[]>([]);
  const [baselineCategory, setBaselineCategory] = useState("");
  const [baselineVersion, setBaselineVersion] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftCategory, setDraftCategory] = useState("");
  const [draftVersion, setDraftVersion] = useState("");
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [rightPanelWidth, setRightPanelWidth] = useState(RIGHT_PANEL_DEFAULT);
  const workspaceRef = useRef<HTMLElement>(null);
  const draggingRef = useRef(false);
  const workflowRunRef = useRef(0);

  const draftVersionOptions = useMemo(
    () => versionsForCategory(allVersions, draftCategory),
    [allVersions, draftCategory],
  );

  const baselineSelected = Boolean(baselineCategory && baselineVersion);

  const onDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current || !workspaceRef.current) return;
      const rect = workspaceRef.current.getBoundingClientRect();
      const nextRight = rect.right - e.clientX;
      const maxRight = rect.width - LEFT_PANEL_MIN;
      setRightPanelWidth(
        Math.max(RIGHT_PANEL_MIN, Math.min(maxRight, nextRight)),
      );
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  useEffect(() => {
    void (async () => {
      setOptionsLoading(true);
      setOptionsError(null);
      try {
        const [opts, strat] = await Promise.all([
          fetchAttributionOptions(),
          fetchWhatIfStrategies(),
        ]);
        setCategories(opts.category || []);
        setAllVersions(opts.version || []);
        setStrategyCatalog(strat.strategies || []);
      } catch (e) {
        setOptionsError(e instanceof Error ? e.message : "加载预测版本失败");
      } finally {
        setOptionsLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!pickerOpen || optionsLoading || draftCategory || !categories.length) return;
    const cat = categories[0];
    const vers = versionsForCategory(allVersions, cat);
    setDraftCategory(cat);
    setDraftVersion(latestVersion(vers) || "");
  }, [pickerOpen, optionsLoading, draftCategory, categories, allVersions]);

  const openBaselinePicker = () => {
    const cat = baselineCategory || categories[0] || "";
    const vers = versionsForCategory(allVersions, cat);
    const ver = baselineVersion || latestVersion(vers) || "";
    setDraftCategory(cat);
    setDraftVersion(ver);
    setPickerOpen(true);
  };

  const onDraftCategoryChange = (cat: string) => {
    setDraftCategory(cat);
    const vers = versionsForCategory(allVersions, cat);
    setDraftVersion(latestVersion(vers) || "");
  };

  const applyBaselinePayload = (
    items: WhatIfBaselineItem[],
    summary: {
      baseline_qty: number;
      baseline_amount: number;
      months: string[];
      qty_series: number[];
      amount_series?: number[];
    },
    period: string | null,
    costMap: Record<string, number>,
    catalog: WhatIfStrategy[],
    goals?: { vol: string; rev: string },
    elasticityHits?: number,
  ) => {
    const nextRows: SimRow[] = items.map((it) => {
      const opts = strategiesForStatusGroup(catalog, it.status);
      const sid = defaultStrategyId(it.status);
      return {
        ...it,
        sim_qty: it.baseline_qty,
        sim_price: it.plan_price,
        cost_price: costMap[it.sku] ?? null,
        strategyOptions: opts,
        strategy_id: sid,
        traffic_tier: null,
      };
    });
    const months = summary.months || [];
    const qtySeries = (summary.qty_series || []).map((q) =>
      Number(((q || 0) / 10000).toFixed(2)),
    );
    const useVol = goals?.vol ?? goalVol;
    const useRev = goals?.rev ?? goalRev;
    setRows(nextRows);
    setAiRecs(nextRows.map(() => ""));
    setStrategyIds(nextRows.map((r) => r.strategy_id));
    setParams(nextRows.map(() => ""));
    setTrafficTiers(nextRows.map(() => null));
    setChartMonths(months);
    setBaselineSeries(qtySeries);
    setBaselineAmount(summary.baseline_amount || 0);
    setBaselinePeriod(period || months[0] || "");
    setSimulationReady(false);
    setAgentReady(false);
    setKpi(
      computeKpi(nextRows, useVol, useRev, {
        success: null,
        labelMode: "baseline",
        simSeries: qtySeries,
        baselineAmount: summary.baseline_amount || 0,
      }),
    );
    return elasticityHits ?? 0;
  };

  const loadBaseline = async (category: string, version: string) => {
    const runId = ++workflowRunRef.current;
    setLoadingBaseline(true);
    setSimulationReady(false);
    setAgentReady(false);
    try {
      let catalog = strategyCatalog;
      if (!catalog.length) {
        const strat = await fetchWhatIfStrategies();
        catalog = strat.strategies || [];
        setStrategyCatalog(catalog);
      }
      const [res, costMap] = await Promise.all([
        fetchWhatIfBaseline({ category, version, limit: 200 }),
        loadCostMap(category),
      ]);
      if (runId !== workflowRunRef.current) return;
      if (!res.ok) {
        setLogs((prev) => [
          ...prev,
          `> 加载失败: ${res.error || "未找到该版本预测数据"}`,
        ]);
        return;
      }
      applyBaselinePayload(
        res.items || [],
        res.summary,
        res.period,
        costMap,
        catalog,
        undefined,
        res.elasticity_hits,
      );
      const qtyWan = ((res.summary?.baseline_qty || 0) / 10000).toFixed(1);
      const revM = ((res.summary?.baseline_amount || 0) / 1e6).toFixed(1);
      const costHits = (res.items || []).filter((it) => costMap[it.sku]).length;
      const elastHits = res.elasticity_hits ?? 0;
      setLogs((prev) => [
        ...prev,
        `> 已加载基础预测: ${category} / ${version}（${res.period || "-"}）`,
        `> 按型号汇总多渠道预测：${res.total} 个型号，基线销量 ${qtyWan} 万件，销售额 ${revM} 百万元（价格×销量）`,
        `> 已匹配商品成本 ${costHits}/${res.total} 个型号；价格弹性表命中 ${elastHits}/${res.total}`,
        `> 已加载策略目录 ${catalog.length} 条（知识库标准化）`,
      ]);
    } catch (e) {
      if (runId !== workflowRunRef.current) return;
      setLogs((prev) => [
        ...prev,
        `> 加载失败: ${e instanceof Error ? e.message : "网络错误"}`,
      ]);
    } finally {
      if (runId === workflowRunRef.current) setLoadingBaseline(false);
    }
  };

  const confirmBaseline = () => {
    if (!draftCategory || !draftVersion) return;
    setBaselineCategory(draftCategory);
    setBaselineVersion(draftVersion);
    setPickerOpen(false);
    void loadBaseline(draftCategory, draftVersion);
  };

  const chartOption = useMemo<EChartsOption>(() => {
    const labels = chartMonths.length
      ? chartMonths.map(formatMonthLabel)
      : ["--"];
    const base = baselineSeries.length ? baselineSeries : [0];
    const sim = kpi.simSeries.length ? kpi.simSeries : base;
    const goalN = Number(goalVol) || 0;
    const goalLine = labels.map(() => goalN);
    const series: LineSeriesOption[] = [
      {
        name: "基线预测",
        type: "line",
        data: base,
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 4,
        lineStyle: { color: "#9ca3af", type: "dashed", width: 2 },
        itemStyle: { color: "#9ca3af" },
      },
    ];
    if (simulationReady || agentReady) {
      series.push({
        name: "当前模拟结果",
        type: "line",
        data: sim,
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 4,
        lineStyle: { color: "#2563eb", width: 2 },
        itemStyle: { color: "#2563eb" },
        areaStyle: { color: "rgba(37, 99, 235, 0.1)" },
      });
    }
    if (agentReady && goalN > 0) {
      series.push({
        name: "设定目标",
        type: "line",
        data: goalLine,
        smooth: false,
        symbol: "none",
        lineStyle: { color: "#10b981", width: 2, type: "dotted" },
        itemStyle: { color: "#10b981" },
      });
    }
    return {
      tooltip: { trigger: "axis" },
      legend: {
        top: 0,
        textStyle: { fontSize: 10 },
        itemWidth: 10,
        itemHeight: 8,
      },
      grid: { left: 36, right: 16, top: 36, bottom: 28 },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { fontSize: 10, color: "#64748b" },
      },
      yAxis: {
        type: "value",
        name: "万件",
        nameTextStyle: { fontSize: 10, color: "#94a3b8" },
        splitLine: { lineStyle: { color: "#f1f5f9" } },
        axisLabel: { fontSize: 10, color: "#64748b" },
      },
      series,
    };
  }, [agentReady, baselineSeries, chartMonths, goalVol, kpi.simSeries, simulationReady]);

  const progressPct = parseFloat(kpi.progress) || 0;
  const progressOk = progressPct >= 100;
  const cardBorder =
    kpi.success === true
      ? "border-green-500"
      : kpi.success === false
        ? "border-blue-500"
        : "border-gray-300";

  const appendLog = (line: string) => setLogs((prev) => [...prev, line]);

  const resetComputedScenario = (nextRows: SimRow[] = rows) => {
    const baselineRows = nextRows.map((row) => ({
      ...row,
      sim_qty: row.baseline_qty,
      sim_price: row.plan_price,
    }));
    setRows(baselineRows);
    setSimulationReady(false);
    setAgentReady(false);
    setAiRecs(baselineRows.map(() => ""));
    setKpi(
      computeKpi(baselineRows, goalVol, goalRev, {
        success: null,
        labelMode: "baseline",
        simSeries: baselineSeries,
        baselineAmount,
      }),
    );
  };

  const runAgent = async () => {
    if (agentRunning || simRunning) return;
    if (!rows.length) {
      appendLog("> 请先选择基础预测（品类 + 版本号）");
      return;
    }
    const goalVolN = Number(goalVol);
    if (!Number.isFinite(goalVolN) || goalVolN <= 0) {
      appendLog("> 请先填写大于 0 的销量目标，再运行 AI 推荐");
      return;
    }
    const runId = workflowRunRef.current;
    setAgentRunning(true);
    appendLog(`> 正在提交 Agent 优化：销量 ${goalVol} 万件，销售额 ${goalRev}M`);
    const baselineTotal = rows.reduce((sum, row) => sum + row.baseline_qty, 0);
    try {
      if (baselineTotal <= 0) throw new Error("基线销量为 0，无法分配优化目标");
      const modelRows = rows.map((row) => ({
        ...toModelRow(row, "maintain", undefined, null),
        target_qty: row.baseline_qty * goalVolN * 10000 / baselineTotal,
      }));
      const submitted = await submitWhatIfOptimization(goalVolN * 10000, modelRows);
      appendLog(`> 优化任务已提交：${submitted.task_id}`);
      let lastProgress = "";
      const resultRows = await pollWhatIfTask(submitted.task_id, (message) => {
        if (message !== lastProgress) {
          lastProgress = message;
          appendLog(`> ${message}`);
        }
      });
      if (runId !== workflowRunRef.current) return;
      if (resultRows.length !== rows.length) throw new Error("模型返回的优化行数与基线不一致");
      const nextIds: string[] = [];
      const nextParams: string[] = [];
      const nextTiers: (TrafficTierId | null)[] = [];
      const nextRecs: string[] = [];
      const nextRows = rows.map((row, index) => {
        const result = resultRows[index] as WhatIfModelResultRow;
        const sid = result.strategy_id || "maintain";
        const param = result.param || "";
        const tier = (result.traffic_tier || null) as TrafficTierId | null;
        nextIds.push(sid);
        nextParams.push(param);
        nextTiers.push(tier);
        nextRecs.push(
          result.strategy_name
            ? result.effect_note && result.effect_note !== "不变"
              ? `${result.strategy_name}：${result.effect_note}`
              : result.strategy_name
            : result.effect_note || "维持现状",
        );
        return {
          ...row,
          strategy_id: sid,
          traffic_tier: tier,
          sim_qty: Number(result.sim_qty ?? row.baseline_qty),
          sim_price: Number(result.sim_price ?? row.plan_price ?? 0),
        };
      });
      const simSeries = seriesFromRows(nextRows, chartMonths, "sim_qty", baselineSeries);
      setStrategyIds(nextIds);
      setParams(nextParams);
      setTrafficTiers(nextTiers);
      setAiRecs(nextRecs);
      setRows(nextRows);
      setKpi(computeKpi(nextRows, goalVol, goalRev, {
        success: null,
        labelMode: "sim",
        simSeries,
        baselineAmount,
      }));
      setSimulationReady(true);
      setAgentReady(true);
      appendLog("> Agent 优化完成：模型已逐行枚举候选策略并返回最接近目标的结果。");
      setAgentDoneFlash(true);
      window.setTimeout(() => setAgentDoneFlash(false), 2000);
    } catch (e) {
      if (runId === workflowRunRef.current) {
        appendLog(`> Agent 优化失败：${e instanceof Error ? e.message : "网络错误"}`);
      }
    } finally {
      if (runId === workflowRunRef.current) setAgentRunning(false);
    }
  };

  const runSimulation = async () => {
    if (simRunning || agentRunning) return;
    if (!rows.length) {
      appendLog("> 请先选择基础预测（品类 + 版本号）");
      return;
    }
    const runId = workflowRunRef.current;
    setSimRunning(true);
    appendLog("> 正在读取矩阵中的 custom strategy 并提交 icewash 模拟任务…");
    try {
      const modelRows = rows.map((row, index) =>
        toModelRow(
          row,
          strategyIds[index] || row.strategy_id || "maintain",
          params[index] ?? "",
          trafficTiers[index] ?? row.traffic_tier,
        ),
      );
      const submitted = await submitWhatIfSimulation(modelRows);
      appendLog(`> 模拟任务已提交：${submitted.task_id}`);
      let lastProgress = "";
      const resultRows = await pollWhatIfTask(submitted.task_id, (message) => {
        if (message !== lastProgress) {
          lastProgress = message;
          appendLog(`> ${message}`);
        }
      });
      if (runId !== workflowRunRef.current) return;
      if (resultRows.length !== rows.length) throw new Error("模型返回的模拟行数与基线不一致");
      const nextRows = rows.map((row, index) => {
        const result = resultRows[index] as WhatIfModelResultRow;
        return {
          ...row,
          strategy_id: result.strategy_id || strategyIds[index] || row.strategy_id,
          traffic_tier: (result.traffic_tier || trafficTiers[index] || null) as TrafficTierId | null,
          sim_qty: Number(result.sim_qty ?? row.baseline_qty),
          sim_price: Number(result.sim_price ?? row.plan_price ?? 0),
        };
      });
      const simSeries = seriesFromRows(nextRows, chartMonths, "sim_qty", baselineSeries);
      setRows(nextRows);
      setAiRecs(nextRows.map(() => ""));
      setAgentReady(false);
      setSimulationReady(true);
      const nextKpi = computeKpi(nextRows, goalVol, goalRev, {
        success: null,
        labelMode: "sim",
        simSeries,
        baselineAmount,
      });
      setKpi(nextKpi);
      appendLog(`> 模拟预测完成：销售额 ${nextKpi.rev}M，综合毛利率 ${nextKpi.margin}%。`);
      setSimDoneFlash(true);
      window.setTimeout(() => setSimDoneFlash(false), 2000);
    } catch (e) {
      if (runId === workflowRunRef.current) {
        appendLog(`> 沙盘模拟失败：${e instanceof Error ? e.message : "网络错误"}`);
      }
    } finally {
      if (runId === workflowRunRef.current) setSimRunning(false);
    }
  };

  const onStrategyChange = (i: number, sid: string) => {
    const nextIds = [...strategyIds];
    nextIds[i] = sid;
    setStrategyIds(nextIds);
    const nextParams = [...params];
    const nextTiers = [...trafficTiers];
    const meta = rows[i]?.strategyOptions.find((o) => o.id === sid);
    if (sid === "traffic_boost") {
      nextTiers[i] = DEFAULT_TRAFFIC_TIER;
      nextParams[i] =
        TRAFFIC_TIERS.find((t) => t.id === DEFAULT_TRAFFIC_TIER)?.param || "+12%";
    } else {
      nextTiers[i] = null;
      nextParams[i] = meta?.default_param || "";
    }
    setParams(nextParams);
    setTrafficTiers(nextTiers);
    resetComputedScenario(
      rows.map((row, idx) =>
        idx === i ? { ...row, strategy_id: sid, traffic_tier: nextTiers[i] } : row,
      ),
    );
  };

  const onTrafficTierChange = (i: number, tier: TrafficTierId) => {
    const nextTiers = [...trafficTiers];
    nextTiers[i] = tier;
    setTrafficTiers(nextTiers);
    const param = TRAFFIC_TIERS.find((t) => t.id === tier)?.param || "+12%";
    const nextParams = [...params];
    nextParams[i] = param;
    setParams(nextParams);
    resetComputedScenario(
      rows.map((row, idx) => (idx === i ? { ...row, traffic_tier: tier } : row)),
    );
  };

  const onParamChange = (i: number, param: string) => {
    const nextParams = [...params];
    nextParams[i] = param;
    setParams(nextParams);
    resetComputedScenario();
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-gray-100 text-gray-800">
      <header className="flex h-12 shrink-0 items-center justify-between bg-slate-900 px-6 text-white shadow-md">
        <div className="flex items-center gap-3">
          <span className="text-blue-400">▦</span>
          <span className="text-md font-bold tracking-wide">
            SupplyPlan Pro | AI智能经营沙盘
          </span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-gray-400">
            {baselinePeriod
              ? `当前预测月: ${baselinePeriod}`
              : "当前周期: 待选择基线"}
          </span>
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-xs font-bold">
            PM
          </div>
        </div>
      </header>

      <section className="z-10 flex shrink-0 items-center justify-between border-b bg-white px-6 py-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-4">
          {baselineSelected ? (
            <div className="flex items-center gap-2 rounded border border-gray-300 bg-gray-100 px-3 py-1.5 text-sm font-medium text-gray-700">
              <FileArrowDown size={16} className="shrink-0 text-blue-600" />
              <span
                className="max-w-[280px] truncate"
                title={`${baselineCategory} · ${baselineVersion}`}
              >
                {baselineCategory} · {baselineVersion}
              </span>
              {loadingBaseline ? (
                <CircleNotch size={14} className="animate-spin text-blue-500" />
              ) : (
                <button
                  type="button"
                  onClick={openBaselinePicker}
                  title="重新选择基础预测"
                  className="ml-1 flex h-6 w-6 cursor-pointer items-center justify-center rounded border border-gray-300 bg-white text-gray-500 transition hover:bg-gray-50 hover:text-blue-600"
                >
                  <PencilSimple size={12} />
                </button>
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={openBaselinePicker}
              className="flex cursor-pointer items-center gap-2 rounded border border-gray-300 bg-gray-100 px-4 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-200"
            >
              <FileArrowDown size={16} className="text-blue-600" />
              1.选择基础预测（Baseline）
            </button>
          )}
          <span className="text-gray-300">→</span>
          <span className="text-sm font-bold text-gray-600">2. 自定义经营策略</span>
          <span className="text-gray-300">→</span>
          <div className="flex items-center gap-2 rounded border border-blue-100 bg-blue-50 px-3 py-1.5">
            <span className="text-sm font-bold text-blue-800">3. 设定经营目标:</span>
            <span className="text-xs text-gray-600">销量 ≥</span>
            <input
              value={goalVol}
              onChange={(e) => setGoalVol(e.target.value)}
              className="w-12 border-b border-blue-300 bg-transparent text-center text-sm font-bold text-blue-700 outline-none"
            />
            <span className="text-xs text-gray-600">万件 | 销售额 ≥</span>
            <input
              value={goalRev}
              onChange={(e) => setGoalRev(e.target.value)}
              className="w-16 border-b border-blue-300 bg-transparent text-center text-sm font-bold text-blue-700 outline-none"
            />
            <span className="text-xs text-gray-600">百万</span>
            <button
              type="button"
              onClick={() => {
                setGoalVol("");
                setGoalRev("");
              }}
              className="ml-1 rounded border border-blue-200 bg-white px-2 py-1 text-xs text-blue-700 transition hover:bg-blue-100"
            >
              重置
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="mr-2 text-xs text-gray-400">选择工作流引擎：</span>
          <button
            type="button"
            onClick={runAgent}
            disabled={agentRunning || simRunning || loadingBaseline}
            className={`flex cursor-pointer items-center gap-2 rounded bg-purple-600 px-5 py-2 text-sm font-bold text-white shadow-md transition hover:bg-purple-700 disabled:cursor-wait ${
              agentRunning ? "animate-pulse shadow-[0_0_20px_#a78bfa]" : ""
            }`}
          >
            {agentRunning ? (
              <CircleNotch size={16} className="animate-spin" />
            ) : agentDoneFlash ? (
              <span>✓</span>
            ) : (
              <MagicWand size={16} />
            )}
            {agentRunning
              ? "AI 测算中..."
              : agentDoneFlash
                ? "推荐完成"
                : "AI Agent 智能推荐策略"}
          </button>
          <button
            type="button"
            onClick={runSimulation}
            disabled={simRunning || agentRunning || loadingBaseline}
            className="flex cursor-pointer items-center gap-2 rounded bg-blue-600 px-5 py-2 text-sm font-bold text-white shadow-md transition hover:bg-blue-700 disabled:cursor-wait"
          >
            {simRunning ? (
              <CircleNotch size={16} className="animate-spin" />
            ) : simDoneFlash ? (
              <span>✓</span>
            ) : (
              <Play size={16} weight="fill" />
            )}
            {simRunning
              ? "模拟计算中..."
              : simDoneFlash
                ? "模拟完成"
                : "运行沙盘模拟预估"}
          </button>
        </div>
      </section>

      <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4">
        <section className="grid shrink-0 grid-cols-2 gap-4 lg:grid-cols-4">
          <div
            className={`rounded-lg border-l-4 bg-white p-3 shadow transition-colors ${cardBorder}`}
          >
            <div className="mb-1 text-xs font-semibold text-gray-500">
              预计总销量 (万件)
            </div>
            <div className="flex items-end justify-between">
              <div className="text-2xl font-bold text-gray-800">{kpi.vol}</div>
              <div
                className={`text-sm font-medium ${
                  kpi.success === true
                    ? "text-green-500"
                    : kpi.success === false
                      ? "text-yellow-500"
                      : "text-gray-400"
                }`}
              >
                {kpi.volDiff}
              </div>
            </div>
            <div className="mt-1 text-xs text-gray-400">
              目标: {goalVol} | 差距:{" "}
              <span className={kpi.success ? "text-green-500" : "text-red-500"}>
                {kpi.volGap}
              </span>
            </div>
          </div>
          <div
            className={`rounded-lg border-l-4 bg-white p-3 shadow transition-colors ${cardBorder}`}
          >
            <div className="mb-1 text-xs font-semibold text-gray-500">
              预计销售额 (百万元)
            </div>
            <div className="flex items-end justify-between">
              <div className="text-2xl font-bold text-gray-800">{kpi.rev}</div>
              <div
                className={`text-sm font-medium ${
                  kpi.success === true
                    ? "text-green-500"
                    : kpi.success === false
                      ? "text-yellow-500"
                      : "text-gray-400"
                }`}
              >
                {kpi.revDiff}
              </div>
            </div>
            <div className="mt-1 text-xs text-gray-400">
              目标: {goalRev} | 差距:{" "}
              <span className={kpi.success ? "text-green-500" : "text-red-500"}>
                {kpi.revGap}
              </span>
            </div>
          </div>
          <div className="rounded-lg border-l-4 border-gray-300 bg-white p-3 shadow">
            <div className="mb-1 text-xs font-semibold text-gray-500">综合毛利率</div>
            <div className="flex items-end justify-between">
              <div className="text-2xl font-bold text-gray-800">{kpi.margin}</div>
              <div className="text-sm font-medium text-gray-400">- (基线)</div>
            </div>
            <div className="mt-1 text-xs text-gray-400">安全底线: 22.0%</div>
          </div>
          <div className="rounded-lg border-l-4 border-gray-300 bg-white p-3 shadow">
            <div className="mb-1 text-xs font-semibold text-gray-500">库存周转天数</div>
            <div className="flex items-end justify-between">
              <div className="text-2xl font-bold text-gray-800">{kpi.turn}</div>
              <div className="text-sm font-medium text-gray-400">- (基线)</div>
            </div>
            <div className="mt-1 text-xs text-gray-400">目标: &lt; 40天</div>
          </div>
        </section>

        <section
          ref={workspaceRef}
          className="flex min-h-[420px] min-w-0 flex-1 overflow-hidden"
        >
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg bg-white shadow">
            <div className="flex shrink-0 items-center justify-between border-b bg-gray-50 p-3">
              <h2 className="flex items-center gap-2 text-sm font-bold text-gray-700">
                <span>🎚️</span> 商品经营策略矩阵
              </h2>
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Info size={12} /> 模拟价=计划价×策略；毛利=(模拟价-成本价)×模拟量
              </span>
            </div>

            <div className="min-h-0 flex-1 overflow-auto p-2">
              {loadingBaseline ? (
                <div className="flex h-40 items-center justify-center gap-2 text-sm text-gray-500">
                  <CircleNotch size={16} className="animate-spin" />
                  正在加载该版本预测数据…
                </div>
              ) : rows.length === 0 ? (
                <div className="flex h-40 items-center justify-center text-sm text-gray-400">
                  请先选择品类与预测版本号
                </div>
              ) : (
                <table className="w-full text-left text-sm">
                  <thead className="sticky top-0 bg-gray-100 text-xs text-gray-500">
                    <tr>
                      <th className="p-2">型号</th>
                      <th className="p-2">计划价格</th>
                      <th className="p-2">基线预测</th>
                      <th className="p-2 text-blue-700">模拟预测</th>
                      <th className="p-2 text-emerald-700">模拟销售额</th>
                      <th className="p-2 text-emerald-700">毛利</th>
                      <th className="bg-purple-50 p-2 text-purple-700">
                        <span className="inline-flex items-center gap-1">
                          <Robot size={12} /> Agent建议策略
                        </span>
                      </th>
                      <th className="border-l border-blue-100 bg-blue-50 p-2 text-blue-700">
                        最终执行策略 (可调)
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {rows.map((sku, i) => {
                      const tone = statusTone(sku.status);
                      const { simAmount, grossProfit } = rowMetrics(sku);
                      return (
                        <tr
                          key={`${sku.sku}-${sku.channel_l3 || ""}-${sku.period || ""}-${i}`}
                          className="transition hover:bg-gray-50"
                        >
                          <td className="p-2">
                            <div className="font-medium text-gray-800">{sku.sku}</div>
                            <div
                              className={`text-xs ${
                                tone === "yellow"
                                  ? "text-yellow-600"
                                  : tone === "green"
                                    ? "text-green-600"
                                    : "text-gray-400"
                              }`}
                            >
                              {[sku.series && `系列 ${sku.series}`, sku.status]
                                .filter(Boolean)
                                .join(" · ") || "-"}
                            </div>
                          </td>
                          <td className="p-2 tabular-nums text-gray-700">
                            {formatPrice(sku.plan_price)}
                          </td>
                          <td className="p-2 tabular-nums text-gray-500">
                            {formatQty(sku.baseline_qty)}
                          </td>
                          <td className="p-2 tabular-nums font-medium text-blue-700">
                            {formatQty(sku.sim_qty)}
                          </td>
                          <td className="p-2 tabular-nums text-emerald-700">
                            {formatAmount(simAmount)}
                          </td>
                          <td
                            className={`p-2 tabular-nums font-medium ${
                              grossProfit >= 0 ? "text-emerald-700" : "text-red-600"
                            }`}
                          >
                            {sku.cost_price != null
                              ? formatAmount(grossProfit)
                              : "-"}
                          </td>
                          <td className="bg-purple-50/50 p-2">
                            <div className="text-xs font-medium text-purple-700">
                              {aiRecs[i] || ""}
                            </div>
                          </td>
                          <td className="border-l border-blue-50 bg-blue-50/30 p-2">
                            <select
                              value={strategyIds[i] || sku.strategy_id}
                              onChange={(e) => onStrategyChange(i, e.target.value)}
                              className="mb-1 w-full rounded border p-1 text-xs outline-none focus:border-blue-500"
                            >
                              {sku.strategyOptions.map((opt) => (
                                <option key={opt.id} value={opt.id}>
                                  {opt.name}
                                </option>
                              ))}
                            </select>
                            {(strategyIds[i] || sku.strategy_id) === "traffic_boost" ? (
                              <select
                                value={trafficTiers[i] || DEFAULT_TRAFFIC_TIER}
                                onChange={(e) =>
                                  onTrafficTierChange(
                                    i,
                                    e.target.value as TrafficTierId,
                                  )
                                }
                                className="mb-1 w-full rounded border border-blue-200 bg-white p-1 text-xs outline-none focus:border-blue-500"
                                title="投流强度档位"
                              >
                                {TRAFFIC_TIERS.map((t) => (
                                  <option key={t.id} value={t.id}>
                                    {t.label}（{t.param}）
                                  </option>
                                ))}
                              </select>
                            ) : null}
                            <input
                              value={params[i] || ""}
                              onChange={(e) => onParamChange(i, e.target.value)}
                              placeholder={
                                sku.strategyOptions.find(
                                  (o) => o.id === (strategyIds[i] || sku.strategy_id),
                                )?.param_label || "参数 (如: -10%)"
                              }
                              disabled={
                                !sku.strategyOptions.find(
                                  (o) => o.id === (strategyIds[i] || sku.strategy_id),
                                )?.param_kind ||
                                sku.strategyOptions.find(
                                  (o) => o.id === (strategyIds[i] || sku.strategy_id),
                                )?.param_kind === "none"
                              }
                              className="w-full rounded border p-1 text-xs outline-none disabled:bg-gray-100 disabled:text-gray-400"
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>

          </div>

          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="调整趋势图区域宽度"
            onMouseDown={onDividerMouseDown}
            className="group relative z-10 w-2 shrink-0 cursor-col-resize bg-gray-200 transition-colors hover:bg-blue-400"
          >
            <div className="absolute inset-y-0 -left-1 -right-1" />
            <div className="absolute left-1/2 top-1/2 h-8 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded bg-gray-400 group-hover:bg-white" />
          </div>

          <div
            className="flex shrink-0 flex-col rounded-lg bg-white p-4 shadow"
            style={{
              width: rightPanelWidth,
              minWidth: RIGHT_PANEL_MIN,
            }}
          >
            <div className="mb-2 flex shrink-0 items-center gap-2 text-sm font-bold text-gray-700">
              <ChartLine size={16} /> 预估达成趋势图
            </div>
            <div className="relative mb-4 min-h-0 flex-1">
              <ReactECharts
                option={chartOption}
                style={{ height: "100%", minHeight: 220, width: "100%" }}
                notMerge
                lazyUpdate
              />
            </div>
            <div className="flex h-20 shrink-0 flex-col justify-center rounded border bg-gray-50 p-3">
              <div className="mb-2 flex justify-between text-xs font-bold text-gray-600">
                <span>销售额目标达成率</span>
                <span className={progressOk ? "text-green-600" : "text-blue-600"}>
                  {kpi.progressLabel}
                </span>
              </div>
              <div className="h-2.5 w-full rounded-full bg-gray-200">
                <div
                  className={`h-2.5 rounded-full transition-all duration-1000 ${
                    progressOk ? "bg-green-500" : "bg-blue-600"
                  }`}
                  style={{ width: `${Math.min(Math.max(progressPct, 0), 100)}%` }}
                />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-gray-400">
                <span>基线({kpi.baselineRevM}M)</span>
                <span>目标({goalRev}M)</span>
              </div>
            </div>
          </div>
        </section>
        <section className="h-28 shrink-0 overflow-auto rounded-lg bg-gray-900 p-3 font-mono text-xs text-gray-300 shadow">
          <div className="mb-1 flex items-center gap-1 font-bold text-purple-400">
            <Terminal size={12} /> 预测模型推导日志
          </div>
          <div className="space-y-1">
            {logs.map((line, i) => (
              <div
                key={`${i}-${line.slice(0, 12)}`}
                className={
                  line.includes("目标") || line.includes("完成")
                    ? "text-green-400"
                    : line.includes("任务") || line.includes("提交")
                      ? "text-blue-300"
                      : line.includes("失败")
                        ? "text-red-400"
                        : ""
                }
              >
                {line}
              </div>
            ))}
          </div>
        </section>
      </main>

      {pickerOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setPickerOpen(false)}
          role="presentation"
        >
          <div
            className="w-full max-w-md rounded-lg bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="baseline-picker-title"
          >
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3
                id="baseline-picker-title"
                className="text-sm font-bold text-gray-800"
              >
                选择基础预测（Baseline）
              </h3>
              <button
                type="button"
                onClick={() => setPickerOpen(false)}
                className="flex h-7 w-7 cursor-pointer items-center justify-center rounded text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
                aria-label="关闭"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-4 px-5 py-4">
              {optionsLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <CircleNotch size={14} className="animate-spin" />
                  加载品类与版本…
                </div>
              ) : optionsError ? (
                <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                  {optionsError}
                </div>
              ) : (
                <>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-gray-600">
                      品类
                    </span>
                    <select
                      value={draftCategory}
                      onChange={(e) => onDraftCategoryChange(e.target.value)}
                      className="w-full rounded border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
                    >
                      {categories.length === 0 ? (
                        <option value="">暂无可用品类</option>
                      ) : (
                        categories.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-gray-600">
                      预测版本号
                    </span>
                    <select
                      value={draftVersion}
                      onChange={(e) => setDraftVersion(e.target.value)}
                      className="w-full rounded border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
                    >
                      {draftVersionOptions.length === 0 ? (
                        <option value="">暂无可用版本</option>
                      ) : (
                        draftVersionOptions.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                </>
              )}
            </div>

            <div className="flex justify-end gap-2 border-t px-5 py-3">
              <button
                type="button"
                onClick={() => setPickerOpen(false)}
                className="cursor-pointer rounded border border-gray-300 px-4 py-1.5 text-sm text-gray-600 transition hover:bg-gray-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={confirmBaseline}
                disabled={!draftCategory || !draftVersion || optionsLoading}
                className="cursor-pointer rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
