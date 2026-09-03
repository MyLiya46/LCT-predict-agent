import { useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import type { WorkbenchChartSeries } from "../api";

type MetricMode = "quantity" | "amount";

type Props = {
  data: WorkbenchChartSeries | null;
  loading?: boolean;
};

function formatValue(value: number, mode: MetricMode): string {
  if (mode === "amount") {
    if (value >= 10000) return `${(value / 10000).toFixed(2)}万`;
    return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

export function ForecastTrendChart({ data, loading }: Props) {
  const [mode, setMode] = useState<MetricMode>("quantity");

  const option = useMemo<EChartsOption>(() => {
    const months = data?.months ?? [];
    const values =
      mode === "quantity" ? data?.quantity ?? [] : data?.amount ?? [];
    const yName = mode === "quantity" ? "预测量" : "预测金额";
    const unit = mode === "quantity" ? "台" : "元";

    return {
      grid: { left: 56, right: 24, top: 36, bottom: 40 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params) => {
          const items = Array.isArray(params) ? params : [params];
          const first = items[0];
          if (!first) return "";
          const val = Number(first.value ?? 0);
          return `${first.name}<br/>${yName}：${formatValue(val, mode)}${unit}`;
        },
      },
      xAxis: {
        type: "category",
        name: "预测月份",
        nameLocation: "middle",
        nameGap: 28,
        data: months,
        axisLabel: { color: "#64748b", fontSize: 11 },
        axisLine: { lineStyle: { color: "#e2e8f0" } },
      },
      yAxis: {
        type: "value",
        name: yName,
        nameTextStyle: { color: "#64748b", fontSize: 11 },
        axisLabel: {
          color: "#64748b",
          fontSize: 11,
          formatter: (v: number) => formatValue(v, mode),
        },
        splitLine: { lineStyle: { color: "#f1f5f9", type: "dashed" } },
      },
      series: [
        {
          type: "bar",
          name: yName,
          data: values,
          barMaxWidth: 48,
          itemStyle: {
            color: "#4b7bec",
            borderRadius: [4, 4, 0, 0],
          },
          label: {
            show: months.length > 0,
            position: "top",
            color: "#475569",
            fontSize: 11,
            formatter: (p) => formatValue(Number(p.value ?? 0), mode),
          },
        },
      ],
    };
  }, [data, mode]);

  return (
    <div className="border-b border-border bg-card px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-foreground">预测趋势</h3>
        <div className="flex rounded-lg border border-border bg-white p-0.5 text-[12px]">
          <button
            type="button"
            onClick={() => setMode("quantity")}
            className={`cursor-pointer rounded-md px-3 py-1 transition ${
              mode === "quantity"
                ? "bg-primary text-white"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            预测量
          </button>
          <button
            type="button"
            onClick={() => setMode("amount")}
            className={`cursor-pointer rounded-md px-3 py-1 transition ${
              mode === "amount"
                ? "bg-primary text-white"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            预测金额
          </button>
        </div>
      </div>
      {loading && !data ? (
        <div className="flex h-[260px] items-center justify-center text-sm text-muted-fg">
          图表加载中…
        </div>
      ) : !data?.months?.length ? (
        <div className="flex h-[260px] items-center justify-center text-sm text-muted-fg">
          暂无趋势数据
        </div>
      ) : (
        <ReactECharts
          option={option}
          style={{ height: 260, width: "100%" }}
          notMerge
          lazyUpdate
          opts={{ renderer: "canvas" }}
        />
      )}
    </div>
  );
}
