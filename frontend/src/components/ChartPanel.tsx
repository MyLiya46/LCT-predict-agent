import ReactECharts from "echarts-for-react";
import { ChartLine } from "@phosphor-icons/react";
import { useAppStore } from "../store";
import { Skeleton } from "./InsightPanel";
import type {
  AgentChart,
  AgentChartCard,
  AgentResultEnvelope,
  ChartType,
  CompositeChart,
  StrategyDashboardChart,
} from "../types";
import {
  buildForecastTrendOption,
  buildWaterfallOption,
  isLineBandCard,
  isWaterfallCard,
} from "./agent/ForecastAttributionChart";
import {
  buildAttainmentTrendOption,
  isAttainmentTrendCard,
  isStrategyMatrixCard,
  StrategyMatrixTable,
} from "./agent/StrategyDashboard";

export function chartTypeLabel(type?: ChartType): string {
  if (type === "composite") return "预测 + 白盒归因";
  if (type === "strategy_dashboard") return "策略矩阵 + 达成趋势";
  if (type === "line_band") return "历史实线 + 预测虚线";
  if (type === "bar") return "对比 / 归因";
  if (type === "pie") return "结构占比";
  if (type === "waterfall") return "增减拆解";
  if (type === "strategy_matrix") return "策略矩阵";
  if (type === "attainment_trend") return "累计达成趋势";
  if (type === "legacy" || type === "line") return "趋势对比";
  return type ? `图表（${type}）` : "趋势对比";
}

function isCardChart(chart: AgentChart): chart is CompositeChart | StrategyDashboardChart {
  return (chart.type === "composite" || chart.type === "strategy_dashboard") && Array.isArray(chart.cards);
}

function LegacyChartBody({ chart, height }: { chart: AgentChart; height: number }) {
  const supportedLegacyTypes = new Set([
    "legacy",
    "line_band",
    "bar",
    "line",
    "pie",
    "waterfall",
    "strategy_matrix",
    "attainment_trend",
  ]);
  if (!chart.option || !supportedLegacyTypes.has(chart.type)) {
    return (
      <div className="rounded border border-dashed border-border px-3 py-6 text-center text-sm text-muted-fg">
        暂无可用图表（类型：{chart.type}）
      </div>
    );
  }
  return <ReactECharts option={chart.option} style={{ height, width: "100%" }} notMerge lazyUpdate opts={{ renderer: "canvas" }} />;
}

function ChartCardBody({ card, height }: { card: AgentChartCard; height: number }) {
  if (isLineBandCard(card)) {
    return <ReactECharts option={buildForecastTrendOption(card.data)} style={{ height, width: "100%" }} notMerge lazyUpdate opts={{ renderer: "canvas" }} />;
  }
  if (isWaterfallCard(card)) {
    return <ReactECharts option={buildWaterfallOption(card.data)} style={{ height: Math.max(height, 320), width: "100%" }} notMerge lazyUpdate opts={{ renderer: "canvas" }} />;
  }
  if (isStrategyMatrixCard(card)) {
    return <StrategyMatrixTable data={card.data} compact />;
  }
  if (isAttainmentTrendCard(card)) {
    return <ReactECharts option={buildAttainmentTrendOption(card.data)} style={{ height, width: "100%" }} notMerge lazyUpdate opts={{ renderer: "canvas" }} />;
  }
  return (
    <div className="rounded border border-dashed border-border px-3 py-6 text-center text-sm text-muted-fg">
      暂无可用图表（类型：{card.type}）
    </div>
  );
}

function CompositeChartBody({ chart, height }: { chart: CompositeChart | StrategyDashboardChart; height: number }) {
  if (!chart.cards.length) return <LegacyChartBody chart={chart} height={height} />;
  return (
    <div className="space-y-5">
      {chart.cards.map((card, index) => (
        <section key={`${card.type}-${card.title}-${index}`} aria-label={card.title}>
          <div className="mb-2 text-sm font-semibold">{card.title}</div>
          <ChartCardBody card={card} height={height} />
        </section>
      ))}
    </div>
  );
}

export function ChartBody({
  envelope,
  height = 320,
  typeHint,
}: {
  envelope: AgentResultEnvelope;
  height?: number;
  typeHint?: string;
}) {
  const chart = envelope.chart;
  if (!chart) return null;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm font-semibold">
        <span>可视化图表</span>
        <span className="text-[11px] font-normal text-muted-fg">
          {typeHint || chartTypeLabel(chart.type)}
        </span>
      </div>
      {isCardChart(chart) ? <CompositeChartBody chart={chart} height={height} /> : <LegacyChartBody chart={chart} height={height} />}
    </div>
  );
}

export function ChartPanel() {
  const envelope = useAppStore((s) => s.envelope);
  const loading = useAppStore((s) => s.loading);

  if (loading && !envelope) {
    return <Skeleton title="可视化图表" height="h-72" />;
  }
  if (!envelope?.chart) {
    return (
      <section className="rounded-xl border border-dashed border-border bg-card p-4 text-sm text-muted-fg shadow-panel">
        暂无图表数据
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-panel">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <ChartLine size={18} className="text-primary" aria-hidden />
        可视化图表
        <span className="ml-auto text-[11px] font-normal text-muted-fg">
          {chartTypeLabel(envelope.chart.type)}
        </span>
      </div>
      <ChartBody envelope={envelope} height={320} />
    </section>
  );
}
