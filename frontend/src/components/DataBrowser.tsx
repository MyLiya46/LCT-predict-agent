import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { DownloadSimple, MagnifyingGlass, UploadSimple } from "@phosphor-icons/react";
import {
  fetchWorkbenchChart,
  fetchWorkbenchFilterOptions,
  fetchWorkbenchTable,
  invalidateWorkbenchFilterOptionsCache,
  uploadCostData,
  type WorkbenchChartSeries,
  type WorkbenchFilterDef,
  type WorkbenchFilterOptionsResponse,
  type WorkbenchTableResponse,
} from "../api";
import { ForecastTrendChart } from "./ForecastTrendChart";

export type FilterFieldConfig = {
  /** 隐藏「全部」选项，必须单选 */
  hideAll?: boolean;
  /** 版本号随品类联动，默认选该品类最新一版 */
  linkLatestVersionToCategory?: boolean;
};

type Props = {
  datasets: { key: string; title: string }[];
  initialDataset: string;
  title: string;
  subtitle?: string;
  showSubTabs?: boolean;
  filterConfig?: Record<string, FilterFieldConfig>;
  /** 按行排列筛选字段 key，未列出的字段归入最后一行 */
  filterRows?: string[][];
  /** 在筛选与明细表之间展示预测趋势柱状图 */
  showTrendChart?: boolean;
};

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
  return best?.v;
}

function buildDefaultFilters(
  filterOptions: Record<string, string[]>,
  filterConfig?: Record<string, FilterFieldConfig>,
): Record<string, string> {
  const out: Record<string, string> = {};
  const cats = filterOptions.category || [];
  if (filterConfig?.category?.hideAll && cats.length) {
    out.category = cats[0];
  }
  if (filterConfig?.version?.linkLatestVersionToCategory && out.category) {
    const vers = versionsForCategory(filterOptions.version || [], out.category);
    const latest = latestVersion(vers);
    if (latest) out.version = latest;
  }
  return out;
}

function groupFilterKeys(
  filterDefs: WorkbenchFilterDef[],
  filterRows?: string[][],
): string[][] {
  const allKeys = filterDefs.map((f) => f.key);
  if (!filterRows?.length) return [allKeys];

  const assigned = new Set<string>();
  const groups = filterRows.map((row) => {
    const keys = row.filter((k) => allKeys.includes(k));
    keys.forEach((k) => assigned.add(k));
    return keys;
  });
  const rest = allKeys.filter((k) => !assigned.has(k));
  if (rest.length) {
    if (groups.length >= 2) groups[1] = [...groups[1], ...rest];
    else groups.push(rest);
  }
  return groups.filter((g) => g.length > 0);
}

export function DataBrowser({
  datasets,
  initialDataset,
  title,
  subtitle,
  showSubTabs = true,
  filterConfig,
  filterRows,
  showTrendChart = false,
}: Props) {
  const [dataset, setDataset] = useState(initialDataset);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<WorkbenchTableResponse | null>(null);
  const [chartData, setChartData] = useState<WorkbenchChartSeries | null>(null);
  const [filterMeta, setFilterMeta] = useState<WorkbenchFilterOptionsResponse | null>(null);
  const [filtersReady, setFiltersReady] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const pageSize = 50;
  const filterConfigRef = useRef(filterConfig);
  filterConfigRef.current = filterConfig;

  const load = useCallback(
    async (ds: string, pageNo: number, applied: Record<string, string>) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchWorkbenchTable(ds, {
          ...applied,
          page: pageNo,
          page_size: pageSize,
        });
        setData(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载失败");
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const loadChart = useCallback(
    async (ds: string, applied: Record<string, string>) => {
      if (!showTrendChart) return;
      setChartLoading(true);
      try {
        const res = await fetchWorkbenchChart(ds, applied);
        setChartData(res);
      } catch {
        setChartData(null);
      } finally {
        setChartLoading(false);
      }
    },
    [showTrendChart],
  );

  const loadScopedFilterOptions = useCallback(
    async (ds: string, applied: Record<string, string>, refresh = false) => {
      try {
        // 按品类收窄渠道/状态等；版本列表由后端按品类返回全部，不按当前 version 收窄
        const full = await fetchWorkbenchFilterOptions(ds, {
          refresh,
          category: applied.category,
          version: applied.version,
        });
        setFilterMeta((prev) => {
          if (!prev) return full;
          // 合并：保留完整品类/版本列表，避免被 scoped 覆盖成 1 个
          return {
            ...full,
            filter_options: {
              ...full.filter_options,
              category: prev.filter_options.category?.length
                ? prev.filter_options.category
                : full.filter_options.category,
              version: (() => {
                const a = prev.filter_options.version || [];
                const b = full.filter_options.version || [];
                return a.length >= b.length ? a : b;
              })(),
            },
          };
        });
      } catch {
        /* 保留 essential 筛选项，不阻断表格 */
      }
    },
    [],
  );

  const initFiltersForDataset = useCallback(
    async (ds: string, refreshOptions = false) => {
      setOptionsLoading(true);
      setFiltersReady(false);
      setFilterMeta(null);
      setData(null);
      setChartData(null);
      setError(null);
      try {
        const essential = await fetchWorkbenchFilterOptions(ds, {
          refresh: refreshOptions,
          essential: filterConfigRef.current != null,
        });
        setFilterMeta(essential);
        const initial = buildDefaultFilters(
          essential.filter_options,
          filterConfigRef.current,
        );
        setDraft(initial);
        setFilters(initial);
        setPage(1);
        setFiltersReady(true);
        void loadScopedFilterOptions(ds, initial, refreshOptions);
      } catch (e) {
        setError(e instanceof Error ? e.message : "筛选项加载失败");
        setFilterMeta(null);
        setFiltersReady(false);
      } finally {
        setOptionsLoading(false);
      }
    },
    [loadScopedFilterOptions],
  );

  useEffect(() => {
    setDataset(initialDataset);
    void initFiltersForDataset(initialDataset);
  }, [initialDataset, initFiltersForDataset]);

  useEffect(() => {
    if (!filtersReady) return;
    void load(dataset, page, filters);
  }, [dataset, page, filters, filtersReady, load]);

  useEffect(() => {
    if (!filtersReady || !showTrendChart) return;
    void loadChart(dataset, filters);
  }, [dataset, filters, filtersReady, loadChart, showTrendChart]);

  const filterDefs: WorkbenchFilterDef[] =
    filterMeta?.filters || data?.filters || [];
  const options = filterMeta?.filter_options || {};
  const filterDefMap = useMemo(
    () => new Map(filterDefs.map((f) => [f.key, f])),
    [filterDefs],
  );
  const filterRowGroups = useMemo(
    () => groupFilterKeys(filterDefs, filterRows),
    [filterDefs, filterRows],
  );

  const renderFilterField = (key: string) => {
    const f = filterDefMap.get(key);
    if (!f) return null;

    const allOpts = options[f.key] || [];
    const hideAll = filterConfig?.[f.key]?.hideAll;
    const opts =
      f.key === "version" && filterConfig?.version?.linkLatestVersionToCategory
        ? versionsForCategory(allOpts, draft.category || filters.category || "")
        : allOpts;
    const isText = f.key === "sku";
    const selectValue = draft[f.key] || (hideAll && opts.length ? opts[0] : "");
    const controlWidth =
      f.key === "version"
        ? "w-[200px]"
        : f.key === "category"
          ? "w-[88px]"
          : f.key === "sku"
            ? "w-[140px]"
            : "w-[120px]";

    return (
      <label
        key={f.key}
        className="flex items-center gap-2 text-[11px] text-muted-fg"
      >
        <span className="shrink-0 whitespace-nowrap">{f.label}</span>
        {isText ? (
          <input
            value={draft[f.key] || ""}
            onChange={(e) => onFilterChange(f.key, e.target.value)}
            placeholder="支持模糊"
            className={`h-8 ${controlWidth} rounded-lg border border-border bg-white px-2.5 text-[13px] text-foreground outline-none focus:border-primary/40 focus:ring-2 focus:ring-primary/15`}
          />
        ) : (
          <select
            value={selectValue}
            onChange={(e) => onFilterChange(f.key, e.target.value)}
            className={`h-8 ${controlWidth} rounded-lg border border-border bg-white px-2.5 text-[13px] text-foreground outline-none focus:border-primary/40 focus:ring-2 focus:ring-primary/15`}
          >
            {!hideAll ? <option value="">全部</option> : null}
            {opts.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        )}
      </label>
    );
  };


  const onSwitchDataset = (key: string) => {
    setDataset(key);
    void initFiltersForDataset(key);
  };

  const onSearch = () => {
    setPage(1);
    setFilters({ ...draft });
  };

  const onReset = () => {
    const initial = buildDefaultFilters(options, filterConfig);
    setDraft(initial);
    setFilters(initial);
    setPage(1);
  };

  const onFilterChange = (key: string, value: string) => {
    const next = { ...draft, [key]: value };
    if (key === "category" && filterConfig?.version?.linkLatestVersionToCategory) {
      const vers = versionsForCategory(options.version || [], value);
      const latest = latestVersion(vers);
      if (latest) next.version = latest;
      setDraft(next);
      setPage(1);
      setFilters(next);
      void loadScopedFilterOptions(dataset, next);
      return;
    }
    // 品类单选：切换后立即查询
    if (key === "category" && filterConfig?.category?.hideAll) {
      setDraft(next);
      setPage(1);
      setFilters(next);
      void loadScopedFilterOptions(dataset, next);
      return;
    }
    setDraft(next);
  };

  const totalPages = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, Math.ceil(data.total / data.page_size));
  }, [data]);

  const exportCsv = async () => {
    if (!data?.total || !data.columns.length) return;
    setExporting(true);
    try {
      const exportPageSize = 200;
      const pages = Math.max(1, Math.ceil(data.total / exportPageSize));
      const allRows: Record<string, unknown>[] = [];
      for (let p = 1; p <= pages; p += 1) {
        const res = await fetchWorkbenchTable(dataset, {
          ...filters,
          page: p,
          page_size: exportPageSize,
        });
        allRows.push(...res.rows);
      }
      const headers = data.columns.map((c) => c.title).join(",");
      const lines = allRows.map((row) =>
        data.columns.map((c) => JSON.stringify(row[c.key] ?? "")).join(","),
      );
      const blob = new Blob([[headers, ...lines].join("\n")], {
        type: "text/csv;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${dataset}-all-${data.total}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  const onUploadCostFile = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const result = await uploadCostData(file);
      invalidateWorkbenchFilterOptionsCache("cost_data");
      setPage(1);
      await initFiltersForDataset(dataset, true);
      setError(null);
      window.alert(
        `上传成功：覆盖更新 ${result.upserted} 条${result.skipped ? `，跳过 ${result.skipped} 条无效行` : ""}。`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
    }
  };

  const showCostUpload = dataset === "cost_data";

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-xs text-muted-fg">{subtitle}</p> : null}
        </div>
        {data ? (
          <span className="rounded-md bg-primary/5 px-2 py-1 text-[11px] font-medium text-primary">
            {data.title} · {data.total} 条
          </span>
        ) : null}
      </div>

      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-panel">
        {showSubTabs && datasets.length > 1 && (
          <div className="flex shrink-0 gap-0 overflow-x-auto border-b border-border px-2">
            {datasets.map((d) => (
              <button
                key={d.key}
                type="button"
                onClick={() => onSwitchDataset(d.key)}
                className={`shrink-0 cursor-pointer border-b-2 px-3.5 py-3 text-[13px] transition ${
                  dataset === d.key
                    ? "border-primary font-semibold text-primary"
                    : "border-transparent text-muted-fg hover:text-foreground"
                }`}
              >
                {d.title}
              </button>
            ))}
          </div>
        )}

        <div className="flex shrink-0 border-b border-border">
          <div className="min-w-0 flex-1 flex flex-col gap-2 px-3 py-3">
            {filterRowGroups.map((rowKeys, rowIndex) => (
              <div key={rowIndex} className="flex flex-wrap items-center gap-x-4 gap-y-2">
                {rowKeys.map((key) => renderFilterField(key))}
              </div>
            ))}
          </div>
          <div className="flex shrink-0 items-center gap-2 self-stretch border-l border-border bg-muted/20 px-4 py-3">
            <button
              type="button"
              onClick={onSearch}
              className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-[13px] font-medium text-white hover:bg-primary/90"
            >
              <MagnifyingGlass size={14} />
              查询
            </button>
            <button
              type="button"
              onClick={onReset}
              className="inline-flex h-8 cursor-pointer items-center rounded-lg border border-border bg-white px-3 text-[13px] text-foreground hover:bg-muted"
            >
              重置
            </button>
            {showCostUpload ? (
              <>
                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void onUploadCostFile(file);
                  }}
                />
                <button
                  type="button"
                  onClick={() => uploadInputRef.current?.click()}
                  disabled={uploading}
                  className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-lg border border-border bg-white px-2 text-[12px] text-primary hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <UploadSimple size={14} />
                  {uploading ? "上传中…" : "上传数据"}
                </button>
              </>
            ) : null}
            <button
              type="button"
              onClick={() => void exportCsv()}
              disabled={!data?.total || exporting}
              className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-lg px-2 text-[12px] text-primary hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
            >
              <DownloadSimple size={14} />
              {exporting ? "导出中…" : "导出全部"}
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {showTrendChart ? (
            <ForecastTrendChart data={chartData} loading={chartLoading} />
          ) : null}
          {showTrendChart ? (
            <div className="border-b border-border bg-card px-4 py-2 text-[13px] font-semibold text-foreground">
              预测结果数据表
            </div>
          ) : null}
          {optionsLoading && !filtersReady ? (
            <div className="p-6 text-sm text-muted-fg">加载筛选项…</div>
          ) : loading && !data ? (
            <div className="p-6 text-sm text-muted-fg">加载中…</div>
          ) : error ? (
            <div className="m-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          ) : !data?.rows?.length ? (
            <div className="p-8 text-center text-sm text-muted-fg">暂无数据</div>
          ) : (
            <table className="min-w-full text-left text-[13px]">
              <thead className="sticky top-0 z-[1] bg-muted text-[11px] font-semibold text-muted-fg">
                <tr>
                  {data.columns.map((c) => (
                    <th key={c.key} className="whitespace-nowrap border-b border-border px-3 py-2.5">
                      {c.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-slate-50/80">
                    {data.columns.map((c) => (
                      <td
                        key={c.key}
                        className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-foreground"
                      >
                        {renderCell(c.key, row[c.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-between border-t border-border px-3 py-2.5 text-xs text-muted-fg">
          <span>
            共 {data?.total ?? 0} 条 · 第 {page} / {totalPages} 页
            {loading ? " · 刷新中…" : ""}
          </span>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="h-7 cursor-pointer rounded-md border border-border bg-white px-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              上一页
            </button>
            <button
              type="button"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => p + 1)}
              className="h-7 cursor-pointer rounded-md border border-border bg-white px-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function badgeClass(kind: "volatility" | "elasticity", label: string): string {
  const base =
    "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset";
  if (kind === "volatility") {
    if (label.includes("大")) return `${base} bg-amber-50 text-amber-800 ring-amber-200`;
    if (label.includes("小")) return `${base} bg-emerald-50 text-emerald-800 ring-emerald-200`;
    return `${base} bg-slate-50 text-slate-700 ring-slate-200`;
  }
  // 弹性分类
  if (label.includes("价格敏感") || label === "强敏感") {
    return `${base} bg-rose-50 text-rose-800 ring-rose-200`;
  }
  if (label.includes("弱敏感")) {
    return `${base} bg-sky-50 text-sky-800 ring-sky-200`;
  }
  if (label.includes("不敏感") || label.includes("钝感")) {
    return `${base} bg-violet-50 text-violet-800 ring-violet-200`;
  }
  return `${base} bg-slate-50 text-slate-700 ring-slate-200`;
}

function renderCell(key: string, v: unknown): ReactNode {
  if (v === null || v === undefined) return "";

  if (key === "价格弹性系数") {
    const n = typeof v === "number" ? v : Number(String(v).replace(/,/g, ""));
    if (!Number.isFinite(n)) return String(v);
    return n.toFixed(2);
  }

  if (key === "波动分类" || key === "弹性分类") {
    const text = String(v).trim();
    if (!text) return "";
    return (
      <span className={badgeClass(key === "波动分类" ? "volatility" : "elasticity", text)}>
        {text}
      </span>
    );
  }

  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
