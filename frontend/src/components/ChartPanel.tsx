import ReactECharts from "echarts-for-react";
import { ChartLine } from "@phosphor-icons/react";
import { useAppStore } from "../store";
import { Skeleton } from "./InsightPanel";
import type { AgentResultEnvelope, ChartType } from "../types";

export function chartTypeLabel(type?: ChartType): string {
  if (type === "line_band") return "历史实线 + 预测虚线";
  if (type === "bar") return "对比 / 归因";
  if (type === "pie") return "结构占比";
  if (type === "waterfall") return "增减拆解";
  return "趋势对比";
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
  if (!envelope.chart) return null;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm font-semibold">
        <span>可视化图表</span>
        <span className="text-[11px] font-normal text-muted-fg">
          {typeHint || chartTypeLabel(envelope.chart.type)}
        </span>
      </div>
      <ReactECharts
        option={envelope.chart.option}
        style={{ height, width: "100%" }}
        notMerge
        lazyUpdate
        opts={{ renderer: "canvas" }}
      />
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
      <ReactECharts
        option={envelope.chart.option}
        style={{ height: 320, width: "100%" }}
        notMerge
        lazyUpdate
        opts={{ renderer: "canvas" }}
      />
    </section>
  );
}
