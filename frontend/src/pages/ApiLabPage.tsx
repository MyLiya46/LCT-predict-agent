import { FormEvent, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowsClockwise,
  CheckCircle,
  Code,
  PaperPlaneTilt,
  WarningCircle,
} from "@phosphor-icons/react";
import * as api from "../api";

type ProbeResult = Awaited<ReturnType<typeof api.probeAgent>>;

const PRETTY = (v: unknown) => JSON.stringify(v, null, 2);

export function ApiLabPage() {
  const [url, setUrl] = useState("");
  const [headersText, setHeadersText] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingTpl, setLoadingTpl] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [meta, setMeta] = useState<{ mode?: string } | null>(null);

  const loadTemplate = useCallback(async (stream: boolean) => {
    setLoadingTpl(true);
    setError(null);
    try {
      const tpl = await api.fetchAgentProbeTemplate(stream);
      setMeta({ mode: tpl.mode });
      setUrl(tpl.url);
      setHeadersText(PRETTY(tpl.headers));
      setBodyText(PRETTY(tpl.body));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载模板失败");
    } finally {
      setLoadingTpl(false);
    }
  }, []);

  useEffect(() => {
    void loadTemplate(false);
  }, [loadTemplate]);

  const parsedHeaders = useMemo(() => {
    try {
      const value = JSON.parse(headersText) as Record<string, unknown>;
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return { ok: false as const, error: "Headers 必须是 JSON 对象" };
      }
      const headers: Record<string, string> = {};
      for (const [k, v] of Object.entries(value)) {
        headers[k] = v == null ? "" : String(v);
      }
      return { ok: true as const, value: headers };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : "Headers JSON 无效" };
    }
  }, [headersText]);

  const parsedBody = useMemo(() => {
    try {
      const value = JSON.parse(bodyText) as Record<string, unknown>;
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return { ok: false as const, error: "Body 必须是 JSON 对象" };
      }
      return { ok: true as const, value };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : "Body JSON 无效" };
    }
  }, [bodyText]);

  const canSubmit = Boolean(url.trim()) && parsedHeaders.ok && parsedBody.ok && !loading;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !parsedHeaders.ok || !parsedBody.ok) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.probeAgent({
        url: url.trim(),
        headers: parsedHeaders.value,
        body: parsedBody.value,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "调用失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-[var(--color-background)]">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-5 shadow-sm">
        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-primary transition hover:bg-muted"
          >
            <ArrowLeft size={14} /> 工作台
          </Link>
          <div className="h-4 w-px bg-border" />
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-white">
              <Code size={16} weight="bold" aria-hidden />
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight">Agent API 测试</h1>
              <p className="text-[11px] text-muted-fg">
                完整 Headers + Body 原样转发
                {meta?.mode ? ` · ${meta.mode}` : ""}
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={loadingTpl || loading}
            onClick={() => void loadTemplate(false)}
            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border bg-white px-2.5 py-1.5 text-xs transition hover:bg-muted disabled:opacity-50"
          >
            <ArrowsClockwise size={14} className={loadingTpl ? "animate-spin" : ""} />
            阻塞模板
          </button>
          <button
            type="button"
            disabled={loadingTpl || loading}
            onClick={() => void loadTemplate(true)}
            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border bg-white px-2.5 py-1.5 text-xs transition hover:bg-muted disabled:opacity-50"
          >
            流式模板
          </button>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-2">
        <form onSubmit={onSubmit} className="flex min-h-0 flex-col border-r border-border bg-card">
          <div className="space-y-2 border-b border-border px-4 py-3">
            <label className="block text-[11px] font-medium text-muted-fg" htmlFor="probe-url">
              URL
            </label>
            <input
              id="probe-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full rounded-md border border-border bg-white px-2.5 py-1.5 font-mono text-xs outline-none focus:border-primary/50"
              spellCheck={false}
            />
          </div>

          <div className="flex min-h-0 flex-1 flex-col border-b border-border">
            <div className="flex items-center justify-between px-4 py-2">
              <span className="text-xs font-medium">Headers（JSON）</span>
              <span className="text-[11px] text-muted-fg">
                {parsedHeaders.ok ? (
                  <span className="text-accent">有效</span>
                ) : (
                  <span className="text-destructive">{parsedHeaders.error}</span>
                )}
              </span>
            </div>
            <textarea
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
              spellCheck={false}
              className="min-h-[140px] flex-1 resize-none bg-slate-950 px-4 py-3 font-mono text-[12px] leading-relaxed text-sky-100 outline-none"
              aria-label="请求 Headers"
            />
          </div>

          <div className="flex min-h-0 flex-[1.4] flex-col">
            <div className="flex items-center justify-between px-4 py-2">
              <span className="text-xs font-medium">Body（JSON）</span>
              <span className="text-[11px] text-muted-fg">
                {parsedBody.ok ? (
                  <span className="text-accent">有效</span>
                ) : (
                  <span className="text-destructive">{parsedBody.error}</span>
                )}
              </span>
            </div>
            <textarea
              value={bodyText}
              onChange={(e) => setBodyText(e.target.value)}
              spellCheck={false}
              className="min-h-0 flex-1 resize-none bg-slate-950 px-4 py-3 font-mono text-[12px] leading-relaxed text-emerald-100 outline-none"
              aria-label="请求 Body"
            />
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
            <p className="text-[11px] text-muted-fg">后端原样转发，不合并、不脱敏、不改写</p>
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <PaperPlaneTilt size={16} weight="fill" />
              {loading ? "调用中…" : "发送"}
            </button>
          </div>
        </form>

        <section className="flex min-h-0 flex-col overflow-hidden bg-[var(--color-background)]">
          <div className="border-b border-border bg-card px-4 py-2 text-xs font-medium">响应结果</div>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
            {error && (
              <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-destructive">
                <WarningCircle size={16} className="mt-0.5 shrink-0" />
                <pre className="whitespace-pre-wrap break-all font-sans">{error}</pre>
              </div>
            )}
            {!result && !error && !loading && (
              <div className="rounded-xl border border-dashed border-border bg-card px-6 py-12 text-center text-sm text-muted-fg">
                编辑完整 Headers 与 Body 后发送；右侧展示实际上游请求与原始响应。
              </div>
            )}
            {loading && (
              <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-fg">
                正在调用 Agent…
              </div>
            )}
            {result && (
              <>
                <div
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${
                    result.ok ? "bg-emerald-50 text-accent" : "bg-rose-50 text-destructive"
                  }`}
                >
                  {result.ok ? <CheckCircle size={14} /> : <WarningCircle size={14} />}
                  {result.ok ? "成功" : "失败"}
                  {result.status_code != null ? ` · HTTP ${result.status_code}` : ""}
                  {result.latency_ms != null ? ` · ${result.latency_ms} ms` : ""}
                  {result.response_mode ? ` · ${result.response_mode}` : ""}
                </div>

                {result.answer != null && String(result.answer).length > 0 && (
                  <Panel title="answer">
                    <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-foreground">
                      {String(result.answer)}
                    </pre>
                  </Panel>
                )}

                {result.error && (
                  <Panel title="error">
                    <pre className="whitespace-pre-wrap break-all text-xs text-destructive">
                      {String(result.error)}
                    </pre>
                  </Panel>
                )}

                <Panel title="实际上游请求 request">
                  <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-slate-700">
                    {PRETTY(result.request)}
                  </pre>
                </Panel>

                {result.response != null && (
                  <Panel title="response（blocking）">
                    <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-slate-700">
                      {PRETTY(result.response)}
                    </pre>
                  </Panel>
                )}

                {Array.isArray(result.events) && result.events.length > 0 && (
                  <Panel title={`events（streaming · ${result.events.length}）`}>
                    <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-slate-700">
                      {PRETTY(result.events)}
                    </pre>
                  </Panel>
                )}

                <Panel title="完整 probe 回包">
                  <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-slate-700">
                    {PRETTY(result)}
                  </pre>
                </Panel>
              </>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="border-b border-border bg-muted/50 px-3 py-1.5 text-[11px] font-medium text-muted-fg">
        {title}
      </div>
      <div className="max-h-[40vh] overflow-auto px-3 py-2">{children}</div>
    </div>
  );
}
