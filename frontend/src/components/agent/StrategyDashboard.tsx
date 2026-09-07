import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import type {
  AgentChartCard,
  AttainmentTrendChartCard,
  AttainmentTrendData,
  NullableNumber,
  StrategyMatrixChartCard,
  StrategyMatrixData,
} from "../../types";

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无数据";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  return String(value);
}

function asSeries(values: NullableNumber[] | undefined): NullableNumber[] {
  return Array.isArray(values) ? values : [];
}

/** Shared cumulative quantity/revenue option used by the What-if page and chat. */
export function buildAttainmentTrendOption(data: AttainmentTrendData): EChartsOption {
  const months = data.months || [];
  const baselineQty = asSeries(data.baseline?.qty);
  const simulatedQty = asSeries(data.simulated?.qty);
  const targetQty = asSeries(data.target?.qty);
  const baselineAmount = asSeries(data.baseline?.amount);
  const simulatedAmount = asSeries(data.simulated?.amount);
  const targetAmount = asSeries(data.target?.amount);
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        const lines = [String(items[0]?.name ?? "")];
        for (const item of items) {
          const value = item.value;
          if (value === null || value === undefined || value === "") continue;
          lines.push(`${item.marker || ""}${item.seriesName || ""}: ${Number(value).toLocaleString("zh-CN")}`);
        }
        return lines.join("<br/>");
      },
    },
    legend: {
      top: 0,
      textStyle: { fontSize: 10 },
      itemWidth: 10,
      itemHeight: 8,
    },
    grid: { left: 48, right: 24, top: 36, bottom: 32 },
    xAxis: {
      type: "category",
      data: months,
      axisLabel: { fontSize: 10, color: "#64748b" },
    },
    yAxis: [
      {
        type: "value",
        name: "累计销量",
        nameTextStyle: { fontSize: 10, color: "#94a3b8" },
        splitLine: { lineStyle: { color: "#f1f5f9" } },
        axisLabel: { fontSize: 10, color: "#64748b" },
      },
      {
        type: "value",
        name: "累计销售额",
        nameTextStyle: { fontSize: 10, color: "#94a3b8" },
        splitLine: { show: false },
        axisLabel: { fontSize: 10, color: "#64748b" },
      },
    ],
    series: [
      {
        name: "累计基线销量",
        type: "line",
        yAxisIndex: 0,
        data: baselineQty,
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 4,
        lineStyle: { color: "#9ca3af", type: "dashed", width: 2 },
        itemStyle: { color: "#9ca3af" },
      },
      {
        name: "累计模拟销量",
        type: "line",
        yAxisIndex: 0,
        data: simulatedQty,
        smooth: 0.3,
        symbol: "circle",
        symbolSize: 4,
        lineStyle: { color: "#2563eb", width: 2 },
        itemStyle: { color: "#2563eb" },
        areaStyle: { color: "rgba(37, 99, 235, 0.1)" },
      },
      {
        name: "累计目标销量",
        type: "line",
        yAxisIndex: 0,
        data: targetQty,
        smooth: false,
        symbol: "none",
        lineStyle: { color: "#10b981", width: 2, type: "dotted" },
        itemStyle: { color: "#10b981" },
      },
      {
        name: "累计基线销售额",
        type: "line",
        yAxisIndex: 1,
        data: baselineAmount,
        smooth: 0.3,
        symbol: "none",
        lineStyle: { color: "#f59e0b", type: "dashed", width: 1.5 },
        itemStyle: { color: "#f59e0b" },
      },
      {
        name: "累计模拟销售额",
        type: "line",
        yAxisIndex: 1,
        data: simulatedAmount,
        smooth: 0.3,
        symbol: "none",
        lineStyle: { color: "#ef4444", width: 1.5 },
        itemStyle: { color: "#ef4444" },
      },
      {
        name: "累计目标销售额",
        type: "line",
        yAxisIndex: 1,
        data: targetAmount,
        smooth: false,
        symbol: "none",
        lineStyle: { color: "#a855f7", width: 1.5, type: "dotted" },
        itemStyle: { color: "#a855f7" },
      },
    ],
  };
}

export function StrategyMatrixTable({
  data,
  compact = false,
}: {
  data: StrategyMatrixData;
  compact?: boolean;
}) {
  const columns = data.columns || [];
  const rows = data.rows || [];
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className={`min-w-full text-left ${compact ? "text-[11px]" : "text-xs"}`}>
        <thead className="bg-muted text-muted-fg">
          <tr>
            {columns.map((column) => (
              <th key={column.key} className="whitespace-nowrap px-2 py-2 font-medium">
                {column.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row, rowIndex) => (
              <tr key={`${String(row.sku || "row")}-${rowIndex}`} className="border-t border-border hover:bg-muted/50">
                {columns.map((column) => (
                  <td key={column.key} className={`whitespace-nowrap px-2 py-2 ${column.align === "right" ? "text-right" : ""}`}>
                    {displayValue(row[column.key])}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={Math.max(columns.length, 1)} className="px-3 py-5 text-center text-muted-fg">
                暂无策略矩阵数据
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="border-t border-border px-2 py-1.5 text-right text-[11px] text-muted-fg">
        共 {data.total ?? rows.length} 个型号
      </div>
    </div>
  );
}

export function StrategyDashboard({
  matrix,
  trend,
  height = 280,
}: {
  matrix?: StrategyMatrixData;
  trend?: AttainmentTrendData;
  height?: number;
}) {
  if (!matrix && !trend) {
    return <div className="py-8 text-center text-sm text-muted-fg">暂无可用策略图表</div>;
  }
  return (
    <div className="space-y-5">
      {matrix ? (
        <section aria-label="策略矩阵">
          <div className="mb-2 text-sm font-semibold">策略矩阵</div>
          <StrategyMatrixTable data={matrix} compact />
        </section>
      ) : null}
      {trend ? (
        <section aria-label="累计达成趋势">
          <div className="mb-2 text-sm font-semibold">累计达成趋势</div>
          <ReactECharts option={buildAttainmentTrendOption(trend)} style={{ height, width: "100%" }} notMerge lazyUpdate />
        </section>
      ) : null}
    </div>
  );
}

export function isStrategyMatrixCard(card: AgentChartCard): card is StrategyMatrixChartCard {
  return card.type === "strategy_matrix" && typeof card.data === "object" && card.data !== null;
}

export function isAttainmentTrendCard(card: AgentChartCard): card is AttainmentTrendChartCard {
  return card.type === "attainment_trend" && typeof card.data === "object" && card.data !== null;
}
