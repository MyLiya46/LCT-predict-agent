import { useMemo, useState } from "react";
import type { AgentResultEnvelope, ChartType } from "../types";
import { InsightBody, stripRelatedSuggestions } from "./InsightPanel";
import { ChartBody, chartTypeLabel } from "./ChartPanel";
import { TableBody } from "./TablePanel";

type TabId = "insight" | "chart" | "table";

export function hasInlineResult(env?: AgentResultEnvelope | null): boolean {
  if (!env) return false;
  if (env.chart || (env.table?.rows && env.table.rows.length > 0)) return true;
  if (env.update_workspace === false) return false;
  return Boolean(stripRelatedSuggestions(env.text?.markdown || "").trim());
}

function defaultTab(tabs: TabId[]): TabId {
  return tabs[0] || "insight";
}

export function MessageResultCard({
  envelope,
  flush = false,
}: {
  envelope: AgentResultEnvelope;
  flush?: boolean;
}) {
  const markdown = stripRelatedSuggestions(envelope.text?.markdown || "").trim();
  const hasInsight = Boolean(markdown);
  const hasChart = Boolean(envelope.chart);
  const hasTable = Boolean(envelope.table?.rows?.length);

  const tabs = useMemo(() => {
    const next: { id: TabId; label: string }[] = [];
    if (hasInsight) next.push({ id: "insight", label: "分析解读" });
    if (hasChart) next.push({ id: "chart", label: "可视化图表" });
    if (hasTable) next.push({ id: "table", label: "数据表" });
    return next;
  }, [hasInsight, hasChart, hasTable]);

  const [tab, setTab] = useState<TabId>(() => defaultTab(tabs.map((t) => t.id)));
  const active = tabs.some((t) => t.id === tab) ? tab : defaultTab(tabs.map((t) => t.id));

  if (!hasInsight && !hasChart && !hasTable) return null;

  return (
    <div className={`${flush ? "mt-3" : "mx-3 mb-3"} overflow-hidden rounded-xl border border-border bg-[#fbfdff]`}>
      {tabs.length > 0 && (
        <div className="flex gap-0 border-b border-border bg-white px-2" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active === t.id}
              onClick={() => setTab(t.id)}
              className={`mb-[-1px] cursor-pointer border-b-2 px-3.5 py-2.5 text-[13px] font-semibold transition ${
                active === t.id
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-fg hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {active === "insight" && hasInsight && (
        <div className="bg-white px-4 py-3.5" role="tabpanel">
          <InsightBody envelope={envelope} />
        </div>
      )}
      {active === "chart" && hasChart && (
        <div className="bg-white px-4 py-3.5" role="tabpanel">
          <ChartBody
            envelope={envelope}
            height={280}
            typeHint={chartTypeLabel(envelope.chart?.type as ChartType)}
          />
        </div>
      )}
      {active === "table" && hasTable && (
        <div className="bg-white px-4 py-3.5" role="tabpanel">
          <TableBody envelope={envelope} />
        </div>
      )}
    </div>
  );
}
