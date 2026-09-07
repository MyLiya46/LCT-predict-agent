import type {
  AgentResultEnvelope,
  AttainmentTrendData,
  CompositeChart,
  StrategyDashboardChart,
  StrategyMatrixData,
} from "../../types";

const forecastPeriods = ["2026-10", "2026-11", "2026-12"];

const forecastLine = {
  type: "line_band",
  title: "预测曲线",
  data: {
    periods: ["2026-08", "2026-09", ...forecastPeriods],
    history: [80, null, 90, null, null, null],
    forecast: [null, null, 100, 110, 120, 130],
    split_period: "2026-10",
    top_skus: Array.from({ length: 5 }, (_, index) => ({
      rank: index + 1,
      sku: `SKU-${index + 1}`,
      periods: forecastPeriods,
      forecast: [20 + index, 22 + index, 24 + index],
    })),
  },
} satisfies CompositeChart["cards"][number];

const attributionWaterfall = {
  type: "waterfall",
  title: "白盒归因",
  data: {
    sku: "SKU-1",
    xAxis: ["基础销量", "价格", "渠道", "最终预测"],
    placeholder: [90, 90, 95, 0],
    values: [90, 5, 5, 100],
    labels: ["90.0", "+5.0", "+5.0", "100.0"],
    colors: ["#d9d9d9", "#52c41a", "#52c41a", "#003a8c"],
  },
} satisfies CompositeChart["cards"][number];

export const forecastAttributionFixture: AgentResultEnvelope = {
  response_type: "forecast",
  intent: "forecast",
  text: { title: "销量预测", markdown: "预测与 TOP5 白盒归因结果。" },
  chart: {
    type: "composite",
    cards: [forecastLine, attributionWaterfall],
    meta: { status: "completed", evidence: { tools: ["submit_forecast", "get_attribution"] } },
  },
  table: {
    columns: [
      { key: "period", title: "预测月份" },
      { key: "forecast_qty", title: "预测销量", align: "right" },
    ],
    rows: forecastPeriods.map((period, index) => ({ period, forecast_qty: 100 + index * 10 })),
  },
};

const whatIfTrend: AttainmentTrendData = {
  months: ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"],
  cumulative: true,
  baseline: {
    qty: [10, 22, 36, 52, 70, 90],
    amount: [1000, 2200, 3600, 5200, 7000, 9000],
  },
  simulated: {
    qty: [11, 24, 40, 58, 78, 100],
    amount: [1100, 2400, 4000, 5800, 7800, 10000],
  },
  target: {
    qty: [12, 24, 40, 56, 72, 90],
    // Missing price coverage is an explicit gap, never an invented zero.
    amount: [null, null, null, null, null, null],
  },
};

const whatIfMatrix: StrategyMatrixData = {
  columns: [
    { key: "sku", title: "型号" },
    { key: "strategy_name", title: "建议策略" },
    { key: "sim_qty", title: "模拟销量", align: "right" },
    { key: "sim_amount", title: "模拟销售额", align: "right" },
    { key: "cost_status", title: "成本覆盖" },
    { key: "inventory_status", title: "库存状态" },
  ],
  rows: [
    {
      sku: "SKU-A",
      strategy_name: "降价促销",
      sim_qty: 100,
      sim_amount: 10000,
      cost_status: "complete",
      inventory_status: "unavailable",
    },
    {
      sku: "SKU-B",
      strategy_name: "维持现状",
      sim_qty: 80,
      sim_amount: null,
      cost_status: "missing",
      inventory_status: "unavailable",
    },
  ],
  total: 2,
};

export const strategyDashboardFixture: AgentResultEnvelope = {
  response_type: "optimization",
  intent: "whatif",
  text: { title: "销售计划优化", markdown: "策略矩阵与六个月累计达成趋势。" },
  chart: {
    type: "strategy_dashboard",
    cards: [
      { type: "strategy_matrix", title: "策略矩阵", data: whatIfMatrix },
      { type: "attainment_trend", title: "累计达成趋势", data: whatIfTrend },
    ],
  },
  table: { columns: whatIfMatrix.columns, rows: whatIfMatrix.rows, total: whatIfMatrix.total },
};

/** Old history messages keep their single ECharts option unchanged. */
export const legacyEnvelopeFixture: AgentResultEnvelope = {
  response_type: "history",
  intent: "history",
  text: { title: "历史销售", markdown: "历史销量结果。" },
  chart: { type: "line", option: { xAxis: { data: ["2026-01"] }, series: [{ data: [1] }] } },
};

export const expectedResultTabs = ["分析解读", "可视化图表", "数据表"] as const;

function isCompositeChart(value: AgentResultEnvelope["chart"]): value is CompositeChart {
  return Boolean(value && value.type === "composite" && "cards" in value && Array.isArray(value.cards));
}

function isStrategyDashboardChart(value: AgentResultEnvelope["chart"]): value is StrategyDashboardChart {
  return Boolean(value && value.type === "strategy_dashboard" && "cards" in value && Array.isArray(value.cards));
}

export function validateAgentChartFixtures(): boolean {
  const forecastChart = forecastAttributionFixture.chart;
  const whatIfChart = strategyDashboardFixture.chart;
  return (
    isCompositeChart(forecastChart) &&
    forecastChart.cards.length === 2 &&
    forecastChart.cards[0].type === "line_band" &&
    forecastChart.cards[1].type === "waterfall" &&
    isStrategyDashboardChart(whatIfChart) &&
    whatIfChart.cards.length === 2 &&
    whatIfChart.cards[0].type === "strategy_matrix" &&
    whatIfChart.cards[1].type === "attainment_trend" &&
    whatIfTrend.target.amount.every((value) => value === null) &&
    whatIfMatrix.rows.some((row) => row.sim_amount === null)
  );
}
