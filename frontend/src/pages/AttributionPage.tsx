import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { CustomSeriesRenderItem, EChartsOption } from "echarts";
import {
  fetchAttributionDetail,
  fetchAttributionOptions,
  fetchAttributionSkus,
  fetchAttributionTrend,
  type AttributionDetail,
  type AttributionSkuItem,
  type AttributionTrend,
} from "../api";

const COLORS = {
  primary: "#1890ff",
  success: "#52c41a",
  warning: "#fa8c16",
  danger: "#ff4d4f",
};

const TAGS = ["全部", "新品", "主销", "淘汰", "Top5", "Top10"] as const;

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

function statusColor(status: string) {
  if (status === "主销" || status === "在售") return COLORS.success;
  if (status === "新品") return COLORS.primary;
  if (status === "淘汰") return COLORS.danger;
  return "#666";
}

function SectionTitle({ children }: { children: string }) {
  return (
    <div className="mb-4 flex items-center text-sm font-semibold" style={{ color: COLORS.primary }}>
      <span className="mr-1.5">//</span>
      {children}
    </div>
  );
}

function itemKey(item: AttributionSkuItem) {
  return `${item.sku}||${item.channel_l1}||${item.channel_l3}`;
}

export default function AttributionPage() {
  const [categories, setCategories] = useState<string[]>([]);
  const [allVersions, setAllVersions] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [version, setVersion] = useState("");
  const [keyword, setKeyword] = useState("");
  const [tag, setTag] = useState<(typeof TAGS)[number]>("全部");
  const [period, setPeriod] = useState("");
  const [months, setMonths] = useState<string[]>([]);
  const [items, setItems] = useState<AttributionSkuItem[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [detail, setDetail] = useState<AttributionDetail | null>(null);
  const [trend, setTrend] = useState<AttributionTrend | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingTrend, setLoadingTrend] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const versionOptions = useMemo(
    () => versionsForCategory(allVersions, category),
    [allVersions, category],
  );

  const selectedItem = useMemo(
    () => items.find((it) => itemKey(it) === selectedKey) || items[0] || null,
    [items, selectedKey],
  );

  useEffect(() => {
    void (async () => {
      try {
        const opts = await fetchAttributionOptions();
        setCategories(opts.category || []);
        setAllVersions(opts.version || []);
        const cat = opts.category?.[0] || "";
        setCategory(cat);
        const vers = versionsForCategory(opts.version || [], cat);
        setVersion(latestVersion(vers) || "");
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载筛选项失败");
      }
    })();
  }, []);

  const loadList = useCallback(async () => {
    if (!category || !version) return;
    setLoadingList(true);
    setError(null);
    try {
      const res = await fetchAttributionSkus({
        category,
        version,
        keyword: keyword || undefined,
        tag: tag === "全部" ? undefined : tag,
        period: period || undefined,
      });
      setItems(res.items || []);
      setMonths(res.months || []);
      if (!period && res.months?.length) {
        setPeriod(res.months[0]);
      }
      if (res.items?.length) {
        const key = itemKey(res.items[0]);
        setSelectedKey((prev) => {
          if (prev && res.items.some((it) => itemKey(it) === prev)) return prev;
          return key;
        });
      } else {
        setSelectedKey("");
        setDetail(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载型号列表失败");
      setItems([]);
    } finally {
      setLoadingList(false);
    }
  }, [category, version, keyword, tag, period]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (!selectedItem || !category || !version) return;
    void (async () => {
      setLoadingDetail(true);
      try {
        const res = await fetchAttributionDetail({
          category,
          version,
          sku: selectedItem.sku,
          channel_l1: selectedItem.channel_l1 || undefined,
          channel_l3: selectedItem.channel_l3 || undefined,
          period: period || undefined,
        });
        setDetail(res.ok ? res : null);
        if (res.months?.length) setMonths(res.months);
      } catch (e) {
        setDetail(null);
        setError(e instanceof Error ? e.message : "加载归因详情失败");
      } finally {
        setLoadingDetail(false);
      }
    })();
  }, [selectedItem, category, version, period]);

  useEffect(() => {
    if (!selectedItem || !category || !version) {
      setTrend(null);
      return;
    }
    void (async () => {
      setLoadingTrend(true);
      try {
        const res = await fetchAttributionTrend({
          category,
          version,
          sku: selectedItem.sku,
          channel_l1: selectedItem.channel_l1 || undefined,
          channel_l3: selectedItem.channel_l3 || undefined,
        });
        setTrend(res.periods?.length ? res : null);
      } catch {
        setTrend(null);
      } finally {
        setLoadingTrend(false);
      }
    })();
  }, [selectedItem, category, version]);

  const onCategoryChange = (cat: string) => {
    setCategory(cat);
    const vers = versionsForCategory(allVersions, cat);
    setVersion(latestVersion(vers) || "");
    setPeriod("");
    setSelectedKey("");
  };

  const waterfallOption = useMemo<EChartsOption>(() => {
    const a = detail?.waterfall;
    if (!a) return {};
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
          const bar = items[1] ?? items[0];
          if (!bar) return "";
          const idx = Number(bar.dataIndex ?? 0);
          return `${bar.name}<br/>影响值 : ${a.labels[idx] ?? ""}`;
        },
      },
      grid: { left: "5%", right: "5%", bottom: "8%", top: "48px", containLabel: true },
      xAxis: {
        type: "category",
        data: a.xAxis,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#d9d9d9" } },
        axisLabel: {
          color: "#666",
          margin: 16,
          interval: 0,
          rotate: a.xAxis.length > 6 ? 20 : 0,
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
          data: a.placeholder,
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
            formatter: (p) => a.labels[Number(p.dataIndex)] ?? "",
          },
          data: a.values.map((v, i) => ({
            value: v,
            itemStyle: { color: a.colors[i] },
          })),
        },
      ],
    };
  }, [detail]);

  const trendOption = useMemo<EChartsOption>(() => {
    if (!trend?.periods?.length) return {};
    const { periods, history, forecast, split_period: splitPeriod } = trend;
    const hasValue = (value: unknown): value is number | string =>
      typeof value === "number" ||
      (typeof value === "string" && value.trim() !== "" && value !== "-");
    const forecastData = [...forecast];
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
      if (hasValue(history[index])) {
        previousHistoryIndex = index;
        break;
      }
    }
    let nextForecastIndex = -1;
    for (let index = firstForecastIndex + 1; index < forecast.length; index += 1) {
      if (hasValue(forecast[index])) {
        nextForecastIndex = index;
        break;
      }
    }
    const hasTransition =
      lastHistoryIndex >= 0 &&
      firstForecastIndex > lastHistoryIndex &&
      lastHistoryIndex < forecastData.length;
    const transitionSeries = hasTransition
      ? {
          name: "预测衔接",
          type: "custom" as const,
          coordinateSystem: "cartesian2d" as const,
          silent: true,
          z: 3,
          data: [0],
          renderItem: ((_, api) => {
            const start = api.coord([periods[lastHistoryIndex], Number(history[lastHistoryIndex])]);
            const end = api.coord([periods[firstForecastIndex], Number(forecast[firstForecastIndex])]);
            const previous =
              previousHistoryIndex >= 0
                ? api.coord([previousHistoryIndex, Number(history[previousHistoryIndex])])
                : start;
            const next =
              nextForecastIndex >= 0
                ? api.coord([periods[nextForecastIndex], Number(forecast[nextForecastIndex])])
                : end;
            const tension = 0.24;
            return {
              type: "bezierCurve",
              shape: {
                x1: start[0],
                y1: start[1],
                // Match the incoming historical tangent and outgoing forecast
                // tangent so the color change does not create a corner.
                cpx1: start[0] + (start[0] - previous[0]) * tension,
                cpy1: start[1] + (start[1] - previous[1]) * tension,
                cpx2: end[0] - (next[0] - end[0]) * tension,
                cpy2: end[1] - (next[1] - end[1]) * tension,
                x2: end[0],
                y2: end[1],
              },
              style: {
                stroke: COLORS.success,
                fill: "none",
                lineWidth: 2,
              },
            };
          }) as CustomSeriesRenderItem,
        }
      : null;
    const markLine = splitPeriod
      ? {
          symbol: ["none", "none"],
          label: { formatter: "预测起点", position: "end" as const },
          lineStyle: { type: "dashed" as const, color: "#fa8c16" },
          data: [{ xAxis: splitPeriod }],
        }
      : undefined;
    return {
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          const items = Array.isArray(params) ? params : [params];
          const lines = [items[0]?.name ?? ""];
          for (const p of items) {
            const val = p.value;
            if (val === "-" || val === null || val === undefined) continue;
            lines.push(`${p.marker}${p.seriesName}: ${Number(val).toLocaleString("zh-CN")}`);
          }
          return lines.join("<br/>");
        },
      },
      legend: {
        data: ["历史零售量", "预测销量"],
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
          data: forecastData,
        },
        ...(transitionSeries ? [transitionSeries] : []),
      ],
    };
  }, [trend]);

  return (
    <div className="flex h-full min-h-0 flex-col" style={{ background: "#f0f2f5", color: "#333" }}>
      <div className="flex h-14 shrink-0 items-center bg-white px-6 text-lg font-semibold shadow-[0_1px_4px_rgba(0,0,0,0.08)]">
        预测白盒分析工作台
      </div>

      <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-4">
        <aside className="flex w-[38%] min-w-[360px] max-w-[520px] flex-col overflow-hidden rounded-lg bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
          <div className="border-b border-[#f0f0f0] px-5 pb-4 pt-6">
            <SectionTitle>型号列表</SectionTitle>
            <div className="mb-3 flex gap-2">
              <select
                value={category}
                onChange={(e) => onCategoryChange(e.target.value)}
                className="h-8 flex-1 rounded-md border border-[#d9d9d9] px-2 text-xs outline-none focus:border-[#1890ff] focus:ring-2 focus:ring-[#1890ff]/20"
              >
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <select
                value={version}
                onChange={(e) => {
                  setVersion(e.target.value);
                  setPeriod("");
                }}
                className="h-8 min-w-[160px] flex-[1.4] rounded-md border border-[#d9d9d9] px-2 text-xs outline-none focus:border-[#1890ff] focus:ring-2 focus:ring-[#1890ff]/20"
              >
                {versionOptions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索型号..."
              className="mb-3 h-8 w-full rounded-md border border-[#d9d9d9] px-2 text-xs outline-none focus:border-[#1890ff] focus:ring-2 focus:ring-[#1890ff]/20"
            />
            <div className="flex flex-wrap gap-1.5">
              {TAGS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTag(t)}
                  className={`cursor-pointer rounded-xl px-2.5 py-0.5 text-xs transition ${
                    tag === t
                      ? "bg-[#e6f7ff] font-medium text-[#1890ff]"
                      : "bg-[#f5f5f5] text-[#666] hover:bg-[#e6f7ff]"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loadingList && !items.length ? (
              <div className="p-4 text-xs text-[#999]">加载中…</div>
            ) : !items.length ? (
              <div className="p-4 text-xs text-[#999]">暂无数据，请确认已导入归因分析结果</div>
            ) : (
              <table className="w-full table-fixed border-collapse text-xs">
                <thead>
                  <tr>
                    {[
                      ["型号", "22%"],
                      ["1级渠道", "16%"],
                      ["3级渠道", "18%"],
                      ["状态", "14%"],
                      ["最终预测值", "18%"],
                    ].map(([h, w]) => (
                      <th
                        key={h}
                        className="sticky top-0 border-b border-[#f0f0f0] bg-[#fafafa] px-2 py-2.5 text-left font-medium text-[#666]"
                        style={{ width: w }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => {
                    const key = itemKey(it);
                    const active = key === (selectedKey || itemKey(items[0]));
                    return (
                      <tr
                        key={key}
                        onClick={() => setSelectedKey(key)}
                        className={`cursor-pointer border-l-[3px] transition ${
                          active
                            ? "border-l-[#1890ff] bg-[#e6f7ff]"
                            : "border-l-transparent hover:bg-[#fafafa]"
                        }`}
                      >
                        <td className="truncate border-b border-[#f0f0f0] px-2 py-3" title={it.sku}>
                          {it.sku}
                        </td>
                        <td className="truncate border-b border-[#f0f0f0] px-2 py-3" title={it.channel_l1}>
                          {it.channel_l1 || "-"}
                        </td>
                        <td className="truncate border-b border-[#f0f0f0] px-2 py-3" title={it.channel_l3}>
                          {it.channel_l3 || "-"}
                        </td>
                        <td
                          className="border-b border-[#f0f0f0] px-2 py-3"
                          style={{ color: statusColor(it.status) }}
                        >
                          {it.status || "-"}
                        </td>
                        <td className="border-b border-[#f0f0f0] px-2 py-3 text-right">
                          {Number(it.y_pred).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto rounded-lg bg-white p-6 pb-10 shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
          {error ? (
            <div className="mb-4 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-600">
              {error}
            </div>
          ) : null}

          <SectionTitle>预测曲线</SectionTitle>
          <div className="mb-2 inline-block rounded bg-[#e2e2e2] px-2 py-1 text-xl font-bold">
            {selectedItem?.sku || "未选择型号"}
          </div>
          <div className="mb-4 text-[13px] text-[#666]">
            {detail?.meta || selectedItem?.meta || "请选择左侧型号查看归因详情"}
          </div>

          <div className="mb-6 rounded-lg border border-[#f0f0f0] bg-[#fafafa] p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h3 className="mr-2 flex items-center text-base font-semibold">
                <span className="mr-1.5 text-lg">📊</span>
                {detail?.model || detail?.method || "归因拆解"}
              </h3>
              {detail?.status ? (
                <span className="rounded-xl border border-[#ffd591] bg-[#fff7e6] px-2 py-0.5 text-xs text-[#fa8c16]">
                  {detail.status}
                </span>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-5 text-[13px] text-[#666]">
              <span>
                上月实际{" "}
                <strong className="ml-1 font-semibold text-[#333]">
                  {detail ? detail.qty_lag1.toLocaleString("zh-CN") : "-"}
                </strong>
              </span>
              <span>
                最终预测{" "}
                <strong className="ml-1 font-semibold text-[#333]">
                  {detail ? detail.y_pred.toLocaleString("zh-CN") : "-"}
                </strong>
              </span>
              <span>
                1级渠道{" "}
                <strong className="ml-1 font-semibold text-[#333]">
                  {detail?.channel_l1 || selectedItem?.channel_l1 || "-"}
                </strong>
              </span>
              <span>
                3级渠道{" "}
                <strong className="ml-1 font-semibold text-[#333]">
                  {detail?.channel_l3 || selectedItem?.channel_l3 || "-"}
                </strong>
              </span>
            </div>
          </div>

          <div className="mb-6 rounded-lg border border-[#f0f0f0] bg-white p-4">
            {loadingTrend && !trend ? (
              <div className="flex h-[320px] items-center justify-center text-sm text-[#999]">
                曲线加载中…
              </div>
            ) : !trend?.periods?.length ? (
              <div className="flex h-[320px] items-center justify-center text-sm text-[#999]">
                暂无历史/预测曲线数据
              </div>
            ) : (
              <ReactECharts
                option={trendOption}
                style={{ height: 320, width: "100%" }}
                notMerge
                lazyUpdate
              />
            )}
          </div>

          <div className="mb-10 rounded-lg border border-[#f0f0f0] bg-[#fafafa] p-4">
            <div className="mb-4 flex items-center text-sm font-semibold">
              🔍 预测依据
              <span className="ml-3 rounded border border-[#d9d9d9] bg-white px-2 py-0.5 text-xs font-normal">
                N+1 ~ N+{Math.max(months.length, 1)} 预测月
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(months.length ? months : ["暂无月份"]).map((m) => (
                <button
                  key={m}
                  type="button"
                  disabled={!months.length}
                  onClick={() => setPeriod(m)}
                  className={`cursor-pointer rounded border px-5 py-1.5 text-[13px] transition disabled:cursor-not-allowed ${
                    period === m
                      ? "border-[#1890ff] bg-[#1890ff] text-white"
                      : "border-[#d9d9d9] bg-white text-[#333] hover:border-[#1890ff]"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <SectionTitle>白盒归因</SectionTitle>
          <div className="rounded-lg border border-[#f0f0f0] bg-white p-6">
            {loadingDetail && !detail ? (
              <div className="py-10 text-center text-sm text-[#999]">归因加载中…</div>
            ) : !detail ? (
              <div className="py-10 text-center text-sm text-[#999]">暂无归因数据</div>
            ) : (
              <>
                <div
                  className="mb-8 rounded-sm border-l-4 bg-[#f6ffed] p-4 text-sm leading-relaxed text-[#333]"
                  style={{ borderLeftColor: COLORS.success }}
                  dangerouslySetInnerHTML={{
                    __html: detail.attribution_text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>"),
                  }}
                />
                <ReactECharts
                  option={waterfallOption}
                  style={{ height: 380, width: "100%" }}
                  notMerge
                  lazyUpdate
                />
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
