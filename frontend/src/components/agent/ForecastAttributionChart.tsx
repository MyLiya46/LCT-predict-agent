import ReactECharts from "echarts-for-react";
import type { CustomSeriesRenderItem, EChartsOption } from "echarts";
import type { LineBandChartData, NullableNumber, WaterfallChartData } from "../../types";

const COLORS = {
  primary: "#1890ff",
  success: "#52c41a",
  warning: "#fa8c16",
  danger: "#ff4d4f",
  final: "#003a8c",
};

function hasValue(value: NullableNumber): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Shared history/forecast option used by both the attribution page and chat cards. */
export function buildForecastTrendOption(data: LineBandChartData): EChartsOption {
  const periods = data.periods || [];
  const history = data.history || [];
  const forecast = data.forecast || [];
  const topSkuNames = (data.top_skus || []).slice(0, 5).map((item, index) => `TOP${item.rank || index + 1} ${item.sku}`);
  let lastHistoryIndex = -1;
  let firstForecastIndex = -1;
  history.forEach((value, index) => {
    if (hasValue(value)) lastHistoryIndex = index;
  });
  forecast.forEach((value, index) => {
    if (firstForecastIndex < 0 && hasValue(value)) firstForecastIndex = index;
  });

  let previousHistoryIndex = -1;
  for (let index = lastHistoryIndex - 1; index >= 0; index -= 1) {
    if (hasValue(history[index] ?? null)) {
      previousHistoryIndex = index;
      break;
    }
  }
  let nextForecastIndex = -1;
  for (let index = firstForecastIndex + 1; index < forecast.length; index += 1) {
    if (hasValue(forecast[index] ?? null)) {
      nextForecastIndex = index;
      break;
    }
  }

  const hasTransition =
    lastHistoryIndex >= 0 &&
    firstForecastIndex > lastHistoryIndex &&
    firstForecastIndex < periods.length;
  const transitionSeries = hasTransition
    ? {
        name: "预测衔接",
        type: "custom" as const,
        coordinateSystem: "cartesian2d" as const,
        silent: true,
        z: 3,
        data: [0],
        renderItem: ((_, api) => {
          const start = api.coord([lastHistoryIndex, history[lastHistoryIndex] ?? 0]);
          const end = api.coord([firstForecastIndex, forecast[firstForecastIndex] ?? 0]);
          const previous =
            previousHistoryIndex >= 0
              ? api.coord([previousHistoryIndex, history[previousHistoryIndex] ?? 0])
              : start;
          const next =
            nextForecastIndex >= 0
              ? api.coord([nextForecastIndex, forecast[nextForecastIndex] ?? 0])
              : end;
          const tension = 0.24;
          return {
            type: "bezierCurve",
            shape: {
              x1: start[0],
              y1: start[1],
              cpx1: start[0] + (start[0] - previous[0]) * tension,
              cpy1: start[1] + (start[1] - previous[1]) * tension,
              cpx2: end[0] - (next[0] - end[0]) * tension,
              cpy2: end[1] - (next[1] - end[1]) * tension,
              x2: end[0],
              y2: end[1],
            },
            style: { stroke: COLORS.success, fill: "none", lineWidth: 2 },
          };
        }) as CustomSeriesRenderItem,
      }
    : null;

  const splitPeriod = data.split_period || (firstForecastIndex >= 0 ? periods[firstForecastIndex] : null);
  const markLine = splitPeriod
    ? {
        symbol: ["none", "none"],
        label: { formatter: "预测起点", position: "end" as const },
        lineStyle: { type: "dashed" as const, color: COLORS.warning },
        data: [{ xAxis: splitPeriod }],
      }
    : undefined;

  return {
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        const lines = [String(items[0]?.name ?? "")];
        for (const item of items) {
          const value = item.value;
          if (value === "-" || value === null || value === undefined || value === "") continue;
          lines.push(`${item.marker || ""}${item.seriesName || ""}: ${Number(value).toLocaleString("zh-CN")}`);
        }
        return lines.join("<br/>");
      },
    },
    legend: {
      data: ["历史零售量", "预测销量", ...topSkuNames],
      top: 0,
      right: 0,
      textStyle: { fontSize: 12, color: "#666" },
    },
    grid: { left: 48, right: 24, top: 36, bottom: 32 },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: periods,
      axisLine: { lineStyle: { color: "#d9d9d9" } },
      axisLabel: { color: "#666", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      splitLine: { lineStyle: { color: "#f0f0f0" } },
      axisLabel: { color: "#999", fontSize: 11 },
    },
    series: [
      {
        name: "历史零售量",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        connectNulls: false,
        lineStyle: { width: 2, color: COLORS.primary },
        itemStyle: { color: COLORS.primary },
        data: history,
        markLine,
      },
      {
        name: "预测销量",
        type: "line",
        smooth: true,
        symbol: "diamond",
        symbolSize: 7,
        connectNulls: false,
        lineStyle: { width: 2, type: "dashed", color: COLORS.success },
        itemStyle: { color: COLORS.success },
        data: forecast,
      },
      ...(data.top_skus || []).slice(0, 5).map((item, index) => ({
        name: `TOP${item.rank || index + 1} ${item.sku}`,
        type: "line" as const,
        smooth: true,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 1, type: "dotted" as const, color: ["#722ed1", "#eb2f96", "#13c2c2", "#fa541c", "#2f54eb"][index] },
        itemStyle: { color: ["#722ed1", "#eb2f96", "#13c2c2", "#fa541c", "#2f54eb"][index] },
        data: periods.map((period) => {
          const itemIndex = item.periods.indexOf(period);
          return itemIndex >= 0 ? item.forecast[itemIndex] ?? null : null;
        }),
      })),
      ...(transitionSeries ? [transitionSeries] : []),
    ],
  };
}

/** Shared white-box waterfall option; null values remain gaps instead of zero. */
export function buildWaterfallOption(data: WaterfallChartData): EChartsOption {
  const values = data.values || [];
  const labels = data.labels || [];
  return {
    title: {
      text: "下月销量预测构成拆解",
      left: "center",
      textStyle: { fontSize: 16, fontWeight: "bold", color: "#333" },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        const item = items[1] || items[0];
        if (!item) return "";
        const index = Number(item.dataIndex ?? 0);
        return `${item.name}<br/>影响值 : ${labels[index] || "暂无数据"}`;
      },
    },
    grid: { left: "5%", right: "5%", bottom: "8%", top: "48px", containLabel: true },
    xAxis: {
      type: "category",
      data: data.xAxis || [],
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#d9d9d9" } },
      axisLabel: {
        color: "#666",
        margin: 16,
        interval: 0,
        rotate: (data.xAxis || []).length > 6 ? 20 : 0,
      },
    },
    yAxis: { show: false },
    series: [
      {
        name: "Placeholder",
        type: "bar",
        stack: "Total",
        silent: true,
        itemStyle: { borderColor: "transparent", color: "transparent" },
        emphasis: { itemStyle: { borderColor: "transparent", color: "transparent" } },
        data: data.placeholder || [],
      },
      {
        name: "Value",
        type: "bar",
        stack: "Total",
        barMaxWidth: 80,
        label: {
          show: true,
          position: "top",
          fontWeight: "bold",
          color: "#333",
          formatter: (params) => labels[Number(params.dataIndex)] || "",
        },
        data: values.map((value, index) => ({
          value,
          itemStyle: { color: data.colors?.[index] || COLORS.final },
        })),
      },
    ],
  };
}

export function ForecastAttributionChart({
  line,
  waterfall,
  height = 280,
}: {
  line?: LineBandChartData;
  waterfall?: WaterfallChartData;
  height?: number;
}) {
  if (!line && !waterfall) {
    return <div className="py-8 text-center text-sm text-muted-fg">暂无可用预测/归因图表</div>;
  }
  return (
    <div className="space-y-5">
      {line ? (
        <section aria-label="预测曲线">
          <div className="mb-2 text-sm font-semibold">预测曲线</div>
          <ReactECharts option={buildForecastTrendOption(line)} style={{ height, width: "100%" }} notMerge lazyUpdate />
        </section>
      ) : null}
      {waterfall ? (
        <section aria-label="白盒归因">
          <div className="mb-2 text-sm font-semibold">白盒归因{waterfall.sku ? ` · ${waterfall.sku}` : ""}</div>
          <ReactECharts
            option={buildWaterfallOption(waterfall)}
            style={{ height: Math.max(height, 320), width: "100%" }}
            notMerge
            lazyUpdate
          />
        </section>
      ) : null}
    </div>
  );
}

export function isLineBandCard(card: { type: string; data: unknown }): card is { type: "line_band"; data: LineBandChartData } {
  return card.type === "line_band" && typeof card.data === "object" && card.data !== null;
}

export function isWaterfallCard(card: { type: string; data: unknown }): card is { type: "waterfall"; data: WaterfallChartData } {
  return card.type === "waterfall" && typeof card.data === "object" && card.data !== null;
}
