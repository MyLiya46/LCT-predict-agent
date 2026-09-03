import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpenText, ListChecks } from "@phosphor-icons/react";
import {
  fetchStrategyKnowledge,
  fetchWhatIfStrategies,
  type WhatIfStrategy,
} from "../api";

const STATUS_LABEL: Record<string, string> = {
  eol: "淘汰",
  new: "新品",
  general: "主销/其他",
};

function formatStatuses(statuses: string[]): string {
  return statuses.map((s) => STATUS_LABEL[s] || s).join("、");
}

function formatDefault(s: WhatIfStrategy): string {
  if (s.id === "traffic_boost" && s.tiers?.length) {
    return s.tiers.map((t) => `${t.label} ${t.param}`).join(" / ");
  }
  return s.default_param || "—";
}

export default function StrategyKnowledgePage() {
  const [title, setTitle] = useState("策略知识库");
  const [source, setSource] = useState<string | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [strategies, setStrategies] = useState<WhatIfStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all([fetchStrategyKnowledge(), fetchWhatIfStrategies()])
      .then(([kb, strat]) => {
        if (cancelled) return;
        setTitle(kb.title || "策略知识库");
        setSource(kb.source || null);
        setMarkdown(kb.markdown || "");
        setStrategies(strat.strategies || []);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="h-full min-h-0 overflow-y-auto p-4">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
              <BookOpenText size={20} className="text-primary" aria-hidden />
              {title}
            </h2>
            <p className="mt-0.5 text-xs text-muted-fg">
              标准化目录来自沙盘引擎 · 下方为量化知识库原文
              {source ? ` · ${source}` : ""}
            </p>
          </div>
        </div>

        <section className="overflow-hidden rounded-xl border border-border bg-card shadow-panel">
          <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
            <ListChecks size={16} className="text-primary" aria-hidden />
            <h3 className="text-[13px] font-semibold text-foreground">
              沙盘执行策略目录
            </h3>
            <span className="text-[11px] text-muted-fg">
              与 What-if「执行策略」同源 · {strategies.length} 条 · 区域内可上下滚动
            </span>
          </div>
          {loading && !strategies.length ? (
            <div className="space-y-2 p-4">
              <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
              <div className="h-3 w-full animate-pulse rounded bg-muted" />
            </div>
          ) : (
            <div className="max-h-[min(280px,36vh)] overflow-y-auto overscroll-contain">
              <table className="min-w-full text-left text-[12px]">
                <thead className="sticky top-0 z-[1] bg-muted text-[11px] font-semibold text-muted-fg shadow-[0_1px_0_0_rgba(0,0,0,0.06)]">
                  <tr>
                    <th className="whitespace-nowrap px-3 py-2">策略名称</th>
                    <th className="whitespace-nowrap px-3 py-2">适用状态</th>
                    <th className="whitespace-nowrap px-3 py-2">关联参数</th>
                    <th className="whitespace-nowrap px-3 py-2">默认值 / 档位</th>
                    <th className="whitespace-nowrap px-3 py-2">销量效果</th>
                    <th className="whitespace-nowrap px-3 py-2">价格效果</th>
                    <th className="whitespace-nowrap px-3 py-2">摘要</th>
                    <th className="whitespace-nowrap px-3 py-2 font-mono">id</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((s) => (
                    <tr key={s.id} className="border-t border-slate-100 hover:bg-slate-50/80">
                      <td className="whitespace-nowrap px-3 py-2 font-medium text-foreground">
                        {s.name}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted-fg">
                        {formatStatuses(s.statuses)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {s.param_label || "—"}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-foreground">
                        {formatDefault(s)}
                      </td>
                      <td className="max-w-[160px] px-3 py-2 text-muted-fg">
                        {s.qty_effect}
                      </td>
                      <td className="max-w-[140px] px-3 py-2 text-muted-fg">
                        {s.price_effect}
                      </td>
                      <td className="max-w-[240px] px-3 py-2 text-muted-fg">
                        {s.summary}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] text-slate-500">
                        {s.id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-border bg-card p-5 shadow-panel">
          <h3 className="mb-3 text-[13px] font-semibold text-foreground">
            量化知识库原文
          </h3>
          {loading && !markdown ? (
            <div className="space-y-2 p-2">
              <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
              <div className="h-3 w-full animate-pulse rounded bg-muted" />
              <div className="h-3 w-5/6 animate-pulse rounded bg-muted" />
            </div>
          ) : error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          ) : (
            <div className="insight-prose max-w-4xl">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
