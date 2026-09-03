import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArticleNyTimes } from "@phosphor-icons/react";
import { useAppStore } from "../store";
import type { AgentResultEnvelope } from "../types";

/** 去掉解读正文中的关联推荐（对话区已有「你可能还想问」） */
export function stripRelatedSuggestions(markdown: string): string {
  const text = (markdown || "").trim();
  if (!text) return text;
  const cleaned = text
    .replace(
      /(?:\n{1,2}|^)(?:如果需要进一步分析[^\n]*|建议继续查看[：:]?|你可以继续(?:问|查看)[：:]?|还可以继续[：:]?|相关推荐[：:]?|后续可(?:关注|尝试|提问)[：:]?|#{1,3}\s*(?:联想追问|推荐问题|后续问题|相关问题))[\s\S]*$/imu,
      "",
    )
    .replace(
      /\n*(?:如果需要进一步分析|建议继续查看|你可以继续问)[^\n]*\n?(?:[-*•].*\n?)*\s*$/iu,
      "",
    )
    .trim();
  return cleaned || text;
}

export function InsightBody({ envelope }: { envelope: AgentResultEnvelope }) {
  const markdown = stripRelatedSuggestions(envelope.text.markdown || "");
  return (
    <div>
      {envelope.meta && (
        <div className="mb-2 font-mono text-[11px] text-muted-fg">
          {envelope.meta.tool} · {envelope.meta.latency_ms}ms
        </div>
      )}
      <div className="insight-prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </div>
    </div>
  );
}

export function InsightPanel() {
  const envelope = useAppStore((s) => s.envelope);
  const loading = useAppStore((s) => s.loading);

  if (loading && !envelope) {
    return <Skeleton title="分析解读" height="h-40" />;
  }
  if (!envelope) return null;

  const { text } = envelope;

  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-panel">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <ArticleNyTimes size={18} className="text-primary" aria-hidden />
          {text.title || "分析解读"}
        </div>
      </div>
      <InsightBody envelope={envelope} />
    </section>
  );
}

export function Skeleton({ title, height }: { title: string; height: string }) {
  return (
    <section className={`rounded-xl border border-border bg-card p-4 shadow-panel ${height}`}>
      <div className="mb-3 text-sm font-semibold text-muted-fg">{title}</div>
      <div className="space-y-2">
        <div className="h-3 w-2/3 animate-pulse rounded bg-muted" />
        <div className="h-3 w-full animate-pulse rounded bg-muted" />
        <div className="h-3 w-5/6 animate-pulse rounded bg-muted" />
      </div>
    </section>
  );
}
