export type Intent = "history" | "forecast" | "attribution" | "whatif";

export type ResponseType =
  | "history"
  | "forecast"
  | "attribution"
  | "report"
  | "optimization"
  | "simulation";

export type NullableNumber = number | null;

export interface Metric {
  label: string;
  value: string | number | null;
  unit?: string;
}

export type TextMetrics = Metric[] | Record<string, string | number | null>;

export interface TableColumn {
  key: string;
  title: string;
  align?: "left" | "right" | "center";
}

export type KnownChartType =
  | "legacy"
  | "composite"
  | "strategy_dashboard"
  | "line_band"
  | "bar"
  | "line"
  | "pie"
  | "waterfall"
  | "strategy_matrix"
  | "attainment_trend";

/** Open string union keeps unknown server chart types diagnosable at runtime. */
export type ChartType = KnownChartType | (string & {});

export interface CoverageState {
  value?: number | null;
  status?: string | null;
  reason?: string | null;
  [key: string]: unknown;
}

export interface ChartEvidence {
  tools?: string[];
  versions?: string[];
  categories?: string[];
  forecast_count?: number;
  attribution_count?: number;
  matched_attribution_count?: number;
  [key: string]: unknown;
}

export interface ChartMeta {
  evidence?: ChartEvidence | Record<string, unknown>;
  assumptions?: string[] | Record<string, unknown>;
  coverage?: CoverageState | Record<string, unknown>;
  status?: string | null;
  reason?: string | null;
  [key: string]: unknown;
}

export interface ForecastTopSku {
  rank?: number;
  sku: string;
  periods: string[];
  forecast: NullableNumber[];
  [key: string]: unknown;
}

export interface LineBandChartData {
  periods: string[];
  history: NullableNumber[];
  forecast: NullableNumber[];
  split_period?: string | null;
  top_skus: ForecastTopSku[];
  [key: string]: unknown;
}

export interface WaterfallChartData {
  sku?: string;
  xAxis: string[];
  placeholder: NullableNumber[];
  values: NullableNumber[];
  labels: string[];
  colors: string[];
  [key: string]: unknown;
}

export interface StrategyMatrixData {
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  total: number;
  [key: string]: unknown;
}

export interface CumulativeSeries {
  qty: NullableNumber[];
  amount: NullableNumber[];
  [key: string]: unknown;
}

export interface AttainmentTrendData {
  months: string[];
  cumulative: boolean;
  baseline: CumulativeSeries;
  simulated: CumulativeSeries;
  target: CumulativeSeries;
  [key: string]: unknown;
}

interface ChartCardBase<T extends ChartType, D> {
  type: T;
  title: string;
  data: D;
  meta?: ChartMeta;
}

export type LineBandChartCard = ChartCardBase<"line_band", LineBandChartData>;
export type WaterfallChartCard = ChartCardBase<"waterfall", WaterfallChartData>;
export type StrategyMatrixChartCard = ChartCardBase<"strategy_matrix", StrategyMatrixData>;
export type AttainmentTrendChartCard = ChartCardBase<"attainment_trend", AttainmentTrendData>;
export type UnknownChartCard = ChartCardBase<string, unknown>;
export type AgentChartCard =
  | LineBandChartCard
  | WaterfallChartCard
  | StrategyMatrixChartCard
  | AttainmentTrendChartCard
  | UnknownChartCard;

export interface LegacyChart {
  type: Exclude<KnownChartType, "composite" | "strategy_dashboard">;
  option?: Record<string, unknown>;
  meta?: ChartMeta;
  [key: string]: unknown;
}

export interface UnknownChart {
  type: string;
  option?: Record<string, unknown>;
  meta?: ChartMeta;
  [key: string]: unknown;
}

export interface CompositeChart {
  type: "composite";
  cards: AgentChartCard[];
  option?: Record<string, unknown>;
  meta?: ChartMeta;
  [key: string]: unknown;
}

export interface StrategyDashboardChart {
  type: "strategy_dashboard";
  cards: AgentChartCard[];
  option?: Record<string, unknown>;
  meta?: ChartMeta;
  [key: string]: unknown;
}

export type AgentChart = LegacyChart | CompositeChart | StrategyDashboardChart | UnknownChart;

export interface AgentResultEnvelope {
  /** Legacy route label; response_type is authoritative for new envelopes. */
  intent?: Intent;
  response_type?: ResponseType | string;
  text?: {
    title: string;
    markdown: string;
    metrics?: TextMetrics;
  };
  chart?: AgentChart;
  table?: {
    columns: TableColumn[];
    rows: Record<string, unknown>[];
    total?: number;
  };
  meta?: {
    tool?: string;
    latency_ms?: number;
    cached?: boolean;
    status?: string | null;
    reason?: string | null;
    coverage?: CoverageState | Record<string, unknown>;
    evidence?: ChartEvidence | Record<string, unknown>;
    assumptions?: string[] | Record<string, unknown>;
    [key: string]: unknown;
  };
  /** 联想追问（最多 3 条），点击后作为下一轮提问 */
  follow_ups?: string[];
  /** 是否用本轮结果刷新右侧工作区；false 时仅更新对话框 */
  update_workspace?: boolean;
  /** Agent 处理步骤（回答后可折叠查看） */
  process_steps?: string[];
}

export interface ChatParams {
  category?: string;
  /** @deprecated 兼容旧字段；优先用 skus */
  sku?: string;
  /** 多选 SKU；空数组 = 全部 */
  skus?: string[];
  /** @deprecated 已由 timeMonths 替代 */
  start?: string;
  /** @deprecated 已由 timeMonths 替代 */
  end?: string;
  /** @deprecated 兼容旧字段；优先用 channels */
  channel?: string;
  /** 多选渠道；空数组 = 全部 */
  channels?: string[];
  /** 时间跨度（月）：1|3|6|12，默认 3 */
  timeMonths?: number;
  /** 与 timeMonths 同步，供后端/预测兼容 */
  horizon?: number;
  intent?: Intent;
  assumptions?: Record<string, number>;
  /** 系列 T/V/L/S/Q；空 = 全部 */
  series?: string;
  /** 预测基准月 YYYY-MM / YYYY-MM-01 */
  forecastMonth?: string;
  /** 重新预测：跳过缓存强制调模型 */
  forceRefresh?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  envelope?: AgentResultEnvelope | null;
  /** 本轮思考/处理步骤（优先于 envelope.process_steps） */
  processSteps?: string[];
  /** ISO 时间，用于相对时间展示与悬浮绝对时间 */
  createdAt?: string;
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  pinned?: boolean;
}
