export type Intent = "history" | "forecast" | "attribution" | "whatif";

export interface Metric {
  label: string;
  value: string;
  unit?: string;
}

export interface TableColumn {
  key: string;
  title: string;
  align?: "left" | "right" | "center";
}

export type ChartType = "line_band" | "bar" | "line" | "pie" | "waterfall";

export interface AgentResultEnvelope {
  intent: Intent;
  text: {
    title: string;
    markdown: string;
    metrics?: Metric[];
  };
  chart?: {
    type: ChartType;
    option: Record<string, unknown>;
  };
  table?: {
    columns: TableColumn[];
    rows: Record<string, unknown>[];
  };
  meta?: {
    tool: string;
    latency_ms: number;
    cached?: boolean;
    status?: string;
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
  /** 追问时带上上一轮意图，后端字段 prior_intent */
  prior_intent?: Intent;
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
