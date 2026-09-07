import {
  FormEvent,
  MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type KeyboardEvent,
} from "react";
import {
  ArrowDown,
  CaretDown,
  ChatCircleText,
  Clock,
  ClockCounterClockwise,
  Copy,
  CopySimple,
  PaperPlaneTilt,
  PencilSimple,
  Plus,
  PushPin,
  Trash,
  X,
} from "@phosphor-icons/react";
import { useAppStore } from "../store";
import type { ChatMessage, SessionSummary } from "../types";
import { MessageResultCard, hasInlineResult } from "./MessageResultCard";

const RECOMMENDED_PROMPTS = [
  "查询冰箱近半年销售情况",
  "预测洗衣机未来3个月销量",
  "预测洗衣机TOP5型号销售趋势并分析",
  "帮我制定冰箱下月销售计划",
] as const;

const NEW_TAB_ID = "__new__";
const MAX_RECENT_TABS = 3;
const RECENT_TABS_KEY = "forecast-agent-recent-tabs";
const CHAT_COLUMN = "mx-auto w-full max-w-[800px] px-6";

function readRecentTabs(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_TABS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeRecentTabs(ids: string[]) {
  localStorage.setItem(RECENT_TABS_KEY, JSON.stringify(ids.slice(0, MAX_RECENT_TABS)));
}

export function ChatPanel({ embedded = false }: { embedded?: boolean }) {
  const [text, setText] = useState("");
  const [recentTabIds, setRecentTabIds] = useState<string[]>(() => readRecentTabs());
  const [historyOpen, setHistoryOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [historyHint, setHistoryHint] = useState<string | null>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousSessionIdRef = useRef<string | null>(null);
  const followLatestRef = useRef(true);
  const [showScrollToLatest, setShowScrollToLatest] = useState(false);

  const messages = useAppStore((s) => s.messages);
  const sessions = useAppStore((s) => s.sessions);
  const loading = useAppStore((s) => s.loading);
  const streamingReply = useAppStore((s) => s.streamingReply);
  const stage = useAppStore((s) => s.stage);
  const processSteps = useAppStore((s) => s.processSteps);
  const error = useAppStore((s) => s.error);
  const envelope = useAppStore((s) => s.envelope);
  const send = useAppStore((s) => s.send);
  const params = useAppStore((s) => s.params);
  const newSession = useAppStore((s) => s.newSession);
  const loadSession = useAppStore((s) => s.loadSession);
  const renameSession = useAppStore((s) => s.renameSession);
  const togglePinSession = useAppStore((s) => s.togglePinSession);
  const deleteSession = useAppStore((s) => s.deleteSession);
  const sessionId = useAppStore((s) => s.sessionId);

  const scrollToLatest = useCallback(() => {
    followLatestRef.current = true;
    setShowScrollToLatest(false);
    window.requestAnimationFrame(() => {
      const element = scrollRef.current;
      if (!element) return;
      element.scrollTo({ top: element.scrollHeight, behavior: "auto" });
    });
  }, []);

  const updateFollowState = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    const nearLatest = distance <= 48;
    followLatestRef.current = nearLatest;
    setShowScrollToLatest(!nearLatest);
  }, []);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    element.addEventListener("scroll", updateFollowState, { passive: true });
    updateFollowState();
    return () => element.removeEventListener("scroll", updateFollowState);
  }, [updateFollowState]);

  useEffect(() => {
    if (previousSessionIdRef.current !== sessionId) {
      previousSessionIdRef.current = sessionId;
      followLatestRef.current = true;
      setShowScrollToLatest(false);
    }
    if (followLatestRef.current) scrollToLatest();
  }, [messages, loading, processSteps, stage, sessionId, scrollToLatest]);

  const sendMessage = useCallback(
    (query: string, paramsOverride?: Parameters<typeof send>[1]) => {
      if (!query.trim()) return;
      scrollToLatest();
      void send(query, paramsOverride);
    },
    [scrollToLatest, send],
  );

  const pushRecentTab = useCallback((id: string) => {
    setRecentTabIds((prev) => {
      const next = [id, ...prev.filter((x) => x !== id && x !== NEW_TAB_ID)].slice(
        0,
        MAX_RECENT_TABS,
      );
      writeRecentTabs(next.filter((x) => x !== NEW_TAB_ID));
      return next;
    });
  }, []);

  // 当前会话进入最近标签
  useEffect(() => {
    if (sessionId) pushRecentTab(sessionId);
  }, [sessionId, pushRecentTab]);

  // 清理已删除会话的标签
  useEffect(() => {
    const valid = new Set(sessions.map((s) => s.id));
    setRecentTabIds((prev) => {
      const next = prev.filter((id) => id === NEW_TAB_ID || valid.has(id));
      if (next.length === prev.length && next.every((id, i) => id === prev[i])) return prev;
      writeRecentTabs(next.filter((x) => x !== NEW_TAB_ID));
      return next;
    });
  }, [sessions]);

  useEffect(() => {
    if (!historyOpen) {
      setRenamingId(null);
      setHistoryHint(null);
      return;
    }
    const onDoc = (e: MouseEvent) => {
      if (!historyRef.current?.contains(e.target as Node)) setHistoryOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [historyOpen]);

  const sessionMap = useMemo(() => {
    const m = new Map<string, SessionSummary>();
    sessions.forEach((s) => m.set(s.id, s));
    return m;
  }, [sessions]);

  const openTabs = useMemo(() => {
    const tabs: { id: string; title: string; isNew?: boolean }[] = [];
    for (const id of recentTabIds) {
      if (id === NEW_TAB_ID) {
        tabs.push({ id: NEW_TAB_ID, title: "新对话", isNew: true });
        continue;
      }
      const s = sessionMap.get(id);
      if (s) tabs.push({ id: s.id, title: s.title || "未命名对话" });
    }
    // 无标签且当前为空会话时，显示「新对话」
    if (!tabs.length && !sessionId) {
      tabs.push({ id: NEW_TAB_ID, title: "新对话", isNew: true });
    }
    // 当前会话不在标签中时补上（最多顶掉最旧）
    if (sessionId && !tabs.some((t) => t.id === sessionId)) {
      const s = sessionMap.get(sessionId);
      tabs.unshift({
        id: sessionId,
        title: s?.title || "当前对话",
      });
      return tabs.slice(0, MAX_RECENT_TABS);
    }
    return tabs.slice(0, MAX_RECENT_TABS);
  }, [recentTabIds, sessionMap, sessionId]);

  const activeTabId = sessionId || NEW_TAB_ID;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendMessage(text);
    setText("");
  };

  const askFollowUp = (question: string) => {
    const q = question.trim();
    if (!q || loading) return;
    sendMessage(q, { ...params });
  };

  const lastFollowUps = (() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      if (m.role === "assistant" && m.envelope?.follow_ups?.length) {
        return m.envelope.follow_ups.slice(0, 3);
      }
    }
    return (envelope?.follow_ups || []).slice(0, 3);
  })();

  const handleNewChat = () => {
    setHistoryOpen(false);
    scrollToLatest();
    newSession();
    setRecentTabIds((prev) => {
      const next = [NEW_TAB_ID, ...prev.filter((x) => x !== NEW_TAB_ID)].slice(
        0,
        MAX_RECENT_TABS,
      );
      writeRecentTabs(next.filter((x) => x !== NEW_TAB_ID));
      return next;
    });
  };

  const handleSelectTab = (id: string) => {
    if (id === NEW_TAB_ID) {
      handleNewChat();
      return;
    }
    if (id === sessionId) return;
    followLatestRef.current = true;
    void loadSession(id);
  };

  const handleCloseTab = (e: ReactMouseEvent, id: string) => {
    e.stopPropagation();
    setRecentTabIds((prev) => {
      const next = prev.filter((x) => x !== id);
      writeRecentTabs(next.filter((x) => x !== NEW_TAB_ID));
      // 关掉当前标签 → 切到相邻或新建
      if (id === activeTabId) {
        const fallback = next.find((x) => x !== NEW_TAB_ID) || next[0];
        queueMicrotask(() => {
          if (!fallback || fallback === NEW_TAB_ID) handleNewChat();
          else void loadSession(fallback);
        });
      }
      if (!next.length) {
        queueMicrotask(() => handleNewChat());
        return [NEW_TAB_ID];
      }
      return next;
    });
  };

  const handlePickHistory = (id: string) => {
    setHistoryOpen(false);
    pushRecentTab(id);
    if (id !== sessionId) {
      followLatestRef.current = true;
      void loadSession(id);
    }
  };

  const handleDeleteSession = async (e: ReactMouseEvent, id: string) => {
    e.stopPropagation();
    const session = sessions.find((item) => item.id === id);
    if (!window.confirm(`确认删除会话“${session?.title || "未命名对话"}”？`)) return;
    setHistoryHint(null);
    try {
      await deleteSession(id);
      setRecentTabIds((prev) => {
        const next = prev.filter((item) => item !== id);
        writeRecentTabs(next.filter((item) => item !== NEW_TAB_ID));
        return next;
      });
      if (id === sessionId) {
        newSession();
        setHistoryOpen(false);
      }
    } catch (err) {
      setHistoryHint(err instanceof Error ? err.message : "删除失败");
    }
  };

  const startRename = (e: ReactMouseEvent, s: SessionSummary) => {
    e.stopPropagation();
    setHistoryHint(null);
    setRenamingId(s.id);
    setRenameDraft(s.title || "");
  };

  const commitRename = async () => {
    if (!renamingId) return;
    const next = renameDraft.trim() || "未命名对话";
    const current = sessions.find((s) => s.id === renamingId);
    setRenamingId(null);
    if (current && next === (current.title || "未命名对话")) return;
    try {
      await renameSession(renamingId, next);
    } catch (err) {
      setHistoryHint(err instanceof Error ? err.message : "重命名失败");
    }
  };

  const handleTogglePin = async (e: ReactMouseEvent, id: string) => {
    e.stopPropagation();
    setHistoryHint(null);
    try {
      await togglePinSession(id);
    } catch (err) {
      setHistoryHint(err instanceof Error ? err.message : "置顶失败");
    }
  };

  return (
    <div className="relative flex h-full flex-col">
      {/* 导航：会话标签 + 新建 / 历史（嵌入侧栏模式时隐藏，历史由侧栏承接） */}
      {!embedded && (
      <div className="flex h-11 shrink-0 items-stretch border-b border-border bg-card">
        <div className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
          {openTabs.map((tab) => {
            const active = tab.id === activeTabId;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => handleSelectTab(tab.id)}
                className={`group relative flex max-w-[9.5rem] shrink-0 cursor-pointer items-center gap-1.5 border-r border-border px-2.5 text-left text-xs transition ${
                  active
                    ? "bg-background text-foreground"
                    : "bg-transparent text-muted-fg hover:bg-muted/80 hover:text-foreground"
                }`}
                title={tab.title}
              >
                <ChatCircleText
                  size={14}
                  className={active ? "shrink-0 text-primary" : "shrink-0 opacity-70"}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate font-medium">{tab.title}</span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => handleCloseTab(e, tab.id)}
                  onKeyDown={(e: KeyboardEvent) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleCloseTab(e as unknown as ReactMouseEvent, tab.id);
                    }
                  }}
                  className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded opacity-0 transition hover:bg-slate-200 group-hover:opacity-100 ${
                    active ? "opacity-60" : ""
                  }`}
                  aria-label={`关闭 ${tab.title}`}
                >
                  <X size={10} weight="bold" />
                </span>
              </button>
            );
          })}
        </div>

        <div className="relative flex shrink-0 items-center gap-0.5 border-l border-border px-1.5" ref={historyRef}>
          <IconTooltipButton label="新建对话" onClick={handleNewChat} ariaLabel="新建对话">
            <Plus size={16} weight="bold" />
          </IconTooltipButton>
          <IconTooltipButton
            label="显示历史对话"
            onClick={() => setHistoryOpen((v) => !v)}
            ariaLabel="显示历史对话"
            active={historyOpen}
          >
            <Clock size={16} />
          </IconTooltipButton>

          {historyOpen && (
            <div className="absolute right-0 top-[calc(100%+4px)] z-40 w-72 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
              <div className="border-b border-border px-3 py-2 text-[11px] font-medium text-muted-fg">
                历史对话
              </div>
              {historyHint && (
                <div className="border-b border-rose-100 bg-rose-50 px-3 py-1.5 text-[11px] text-destructive">
                  {historyHint}
                </div>
              )}
              <div className="max-h-64 overflow-y-auto py-1">
                {sessions.length === 0 ? (
                  <p className="px-3 py-4 text-center text-xs text-muted-fg">暂无历史会话</p>
                ) : (
                  sessions.map((s) => {
                    const renaming = renamingId === s.id;
                    return (
                      <div
                        key={s.id}
                        className={`group/item flex items-start gap-1 px-2 py-1.5 transition hover:bg-muted ${
                          s.id === sessionId ? "bg-primary/5" : ""
                        }`}
                      >
                        <div className="mt-1 w-3 shrink-0">
                          {s.pinned ? (
                            <PushPin
                              size={12}
                              weight="fill"
                              className="text-primary"
                              aria-hidden
                            />
                          ) : null}
                        </div>
                        <div className="min-w-0 flex-1">
                          {renaming ? (
                            <input
                              autoFocus
                              value={renameDraft}
                              maxLength={40}
                              onChange={(e) => setRenameDraft(e.target.value)}
                              onClick={(e) => e.stopPropagation()}
                              onKeyDown={(e) => {
                                e.stopPropagation();
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  void commitRename();
                                } else if (e.key === "Escape") {
                                  e.preventDefault();
                                  setRenamingId(null);
                                }
                              }}
                              onBlur={() => void commitRename()}
                              className="w-full rounded border border-primary/40 bg-white px-1.5 py-0.5 text-xs text-foreground outline-none"
                              aria-label="重命名对话"
                            />
                          ) : (
                            <button
                              type="button"
                              onClick={() => handlePickHistory(s.id)}
                              className="flex w-full cursor-pointer flex-col gap-0.5 text-left"
                            >
                              <span className="truncate text-xs font-medium text-foreground">
                                {s.title || "未命名对话"}
                              </span>
                              <span className="text-[10px] text-muted-fg">
                                {formatAbsoluteTime(s.updated_at)}
                              </span>
                            </button>
                          )}
                        </div>
                        {!renaming && (
                          <div
                            className={`flex shrink-0 items-center gap-0.5 transition ${
                              s.pinned
                                ? "opacity-100"
                                : "opacity-0 group-hover/item:opacity-100"
                            }`}
                          >
                            <button
                              type="button"
                              onClick={(e) => void handleTogglePin(e, s.id)}
                              className={`inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-slate-200 hover:text-foreground ${
                                s.pinned ? "opacity-100 text-primary" : ""
                              }`}
                              aria-label={s.pinned ? "取消置顶" : "置顶"}
                              title={s.pinned ? "取消置顶" : "置顶"}
                            >
                              <PushPin size={13} weight={s.pinned ? "fill" : "regular"} />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => startRename(e, s)}
                              className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-slate-200 hover:text-foreground"
                              aria-label="重命名"
                              title="重命名"
                            >
                              <PencilSimple size={13} />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => void handleDeleteSession(e, s.id)}
                              className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-rose-100 hover:text-destructive"
                              aria-label="删除会话"
                              title="删除会话"
                            >
                              <Trash size={13} />
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
      <div className={embedded ? `${CHAT_COLUMN} space-y-5 py-8` : "space-y-4 px-3 py-3"}>
        {messages.length === 0 && (
          <div className="flex flex-col gap-5 pt-6">
            <p className="text-center text-[15px] font-semibold leading-snug text-foreground">
              我是您的AI预测助手，有什么可以帮到你
            </p>
            <div className="space-y-2">
              <div className="px-0.5 text-[11px] text-muted-fg">为你推荐</div>
              <div className="flex flex-col gap-2">
                {RECOMMENDED_PROMPTS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    disabled={loading}
                    onClick={() => askFollowUp(q)}
                    className="cursor-pointer rounded-xl border border-border bg-muted/50 px-3.5 py-2.5 text-left text-xs leading-snug text-foreground transition hover:border-primary/35 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <MessageBlock
              key={m.id}
              align="right"
              createdAt={m.createdAt}
              copyText={m.content}
            >
              <div className="rounded-xl bg-primary px-3 py-2 text-sm leading-relaxed text-white">
                {m.content}
              </div>
            </MessageBlock>
          ) : (
            <MessageBlock
              key={m.id}
              align="left"
              createdAt={m.createdAt}
              copyText={m.envelope?.text?.markdown || m.content}
            >
              <AssistantMessageBubble
                content={m.content}
                steps={m.processSteps || m.envelope?.process_steps || []}
                clampAnswer={m.envelope?.update_workspace !== false}
                envelope={m.envelope}
                floating={embedded}
              />
            </MessageBlock>
          ),
        )}
        {streamingReply && (
          <MessageBlock
            align="left"
            copyText={streamingReply}
          >
            <AssistantMessageBubble
              content={streamingReply}
              steps={[]}
              clampAnswer={false}
              floating={embedded}
            />
          </MessageBlock>
        )}
        {loading && (
          <div className="mr-auto w-full space-y-2 rounded-xl border border-border bg-white px-3 py-2.5 text-xs text-muted-fg">
            <div className="inline-flex items-center gap-2 font-medium text-foreground">
              <ClockCounterClockwise size={14} className="animate-spin text-primary" aria-hidden />
              Agent 处理过程
            </div>
            <ul className="max-h-40 space-y-1.5 overflow-y-auto border-l border-border/80 pl-3">
              {(processSteps.length ? processSteps : [stage || "处理中…"]).map((step, i, arr) => {
                const isLatest = i === arr.length - 1;
                return (
                  <li
                    key={`${i}-${step.slice(0, 24)}`}
                    className={`leading-relaxed ${isLatest ? "text-foreground" : "text-muted-fg/80"}`}
                  >
                    {isLatest ? "▸ " : "· "}
                    {step}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {!loading && lastFollowUps.length > 0 && (
          <div className="mr-auto w-full space-y-2 rounded-xl border border-dashed border-primary/30 bg-primary/[0.03] px-3 py-2.5">
            <div className="text-[11px] font-medium text-muted-fg">你可能还想问</div>
            <div className="flex flex-col gap-1.5">
              {lastFollowUps.map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={loading}
                  onClick={() => askFollowUp(q)}
                  className="cursor-pointer rounded-lg border border-border bg-white px-2.5 py-2 text-left text-xs leading-snug text-foreground transition hover:border-primary/40 hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>

      {showScrollToLatest && (
        <button
          type="button"
          onClick={scrollToLatest}
          className="absolute bottom-[5.75rem] right-4 z-10 inline-flex items-center gap-1 rounded-full border border-border bg-white px-2.5 py-1.5 text-[11px] font-medium text-foreground shadow-md transition hover:border-primary/40 hover:text-primary"
          aria-label="回到底部"
        >
          <ArrowDown size={13} />
          回到底部
        </button>
      )}

      <form onSubmit={onSubmit} className={embedded ? "shrink-0 pb-6 pt-1" : "border-t border-border p-3"}>
        <div className={embedded ? CHAT_COLUMN : undefined}>
        <div className={`flex items-end gap-2 p-2 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/15 ${
          embedded
            ? "rounded-2xl border border-border bg-white shadow-sm"
            : "rounded-xl border border-border bg-muted/40"
        }`}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            placeholder="输入品类/产品/时间等分析问题…"
            className="max-h-28 min-h-[52px] w-full resize-none bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-fg"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage(text);
                setText("");
              }
            }}
          />
          <button
            type="submit"
            disabled={loading || !text.trim()}
            className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-primary text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="发送"
          >
            <PaperPlaneTilt size={18} weight="fill" />
          </button>
        </div>
        </div>
      </form>
    </div>
  );
}

function IconTooltipButton({
  label,
  onClick,
  children,
  ariaLabel,
  active,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  ariaLabel: string;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={`group/tip relative inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-muted-fg transition hover:bg-muted hover:text-foreground ${
        active ? "bg-muted text-foreground" : ""
      }`}
    >
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-[calc(100%+6px)] z-50 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#2a2a2a] px-2.5 py-1 text-[11px] font-medium text-white opacity-0 shadow-md transition group-hover/tip:opacity-100"
      >
        {label}
      </span>
    </button>
  );
}

function MessageBlock({
  children,
  align,
  createdAt,
  copyText,
}: {
  children: ReactNode;
  align: "left" | "right";
  createdAt?: string;
  copyText: string;
}) {
  const [copied, setCopied] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const t = window.setInterval(() => setTick((n) => n + 1), 60_000);
    return () => window.clearInterval(t);
  }, []);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  const relative = formatRelativeTime(createdAt, tick);
  const absolute = formatAbsoluteTime(createdAt);

  return (
    <div className={`flex w-full flex-col gap-1.5 ${align === "right" ? "ml-auto items-end" : "mr-auto items-start"}`}>
      <div className={`min-w-0 ${align === "right" ? "max-w-[420px]" : "w-full"}`}>{children}</div>
      <div
        className={`flex items-center gap-1.5 text-[11px] text-muted-fg ${
          align === "right" ? "flex-row-reverse" : ""
        }`}
      >
        <span className="group/time relative cursor-default">
          <span className="tabular-nums">{relative}</span>
          {absolute && (
            <span
              role="tooltip"
              className="pointer-events-none absolute bottom-[calc(100%+6px)] left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#2a2a2a] px-2.5 py-1 text-[11px] font-medium text-white opacity-0 shadow-md transition group-hover/time:opacity-100"
            >
              {absolute}
            </span>
          )}
        </span>
        <button
          type="button"
          onClick={() => void onCopy()}
          className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-muted hover:text-foreground"
          aria-label={copied ? "已复制" : "复制"}
          title={copied ? "已复制" : "复制"}
        >
          {copied ? <CopySimple size={13} className="text-accent" /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}

function AssistantMessageBubble({
  content,
  steps,
  clampAnswer,
  envelope,
  floating = false,
}: {
  content: string;
  steps: string[];
  clampAnswer: boolean;
  envelope?: ChatMessage["envelope"];
  floating?: boolean;
}) {
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const thinkingListId = useId();
  const [answerExpanded, setAnswerExpanded] = useState(!clampAnswer);
  const plain = stripMd(content);
  const showResult = hasInlineResult(envelope);
  const showAnswer = !showResult;
  const showAnswerToggle = showAnswer && clampAnswer && plain.length > 160;

  return (
    <div
      className={
        floating
          ? "w-full text-foreground"
          : "w-full overflow-hidden rounded-xl border border-border bg-white text-foreground"
      }
    >
      {steps.length > 0 && (
        <div className={floating ? "mb-2 rounded-xl bg-muted/70" : "border-b border-border bg-muted/70"}>
          <button
            type="button"
            onClick={() => setThinkingOpen((v) => !v)}
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left transition hover:bg-slate-100/80"
            aria-expanded={thinkingOpen}
            aria-controls={thinkingListId}
          >
            <CaretDown
              size={14}
              className={`shrink-0 text-primary transition ${thinkingOpen ? "rotate-180" : ""}`}
              aria-hidden
            />
            <span className="text-xs font-semibold text-foreground">思考过程</span>
            <span className="ml-auto text-[11px] text-muted-fg">
              {thinkingOpen ? "收起" : `${steps.length} 步 · 已完成`}
            </span>
          </button>
          {thinkingOpen && (
            <ul id={thinkingListId} className="max-h-40 space-y-1 overflow-y-auto border-l-2 border-border px-3 pb-2.5 pl-5">
              {steps.map((step, i) => {
                const isLast = i === steps.length - 1;
                const inProgress = isLast && /正在|…$|\.\.\.$/.test(step);
                return (
                  <li
                    key={`${i}-${step.slice(0, 24)}`}
                    className={`relative text-[11px] leading-relaxed ${
                      inProgress ? "font-medium text-foreground" : "text-muted-fg"
                    }`}
                  >
                    <span
                      className={`absolute -left-[15px] top-[6px] h-1.5 w-1.5 rounded-full ${
                        inProgress ? "bg-primary" : "bg-slate-300"
                      }`}
                      aria-hidden
                    />
                    {step}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
      {showAnswer && (
        <div className={floating ? "py-1" : "px-3 py-2.5"}>
          <div
            className={`whitespace-pre-wrap leading-relaxed text-foreground ${
              floating ? "text-sm" : "text-xs text-muted-fg"
            } ${!answerExpanded && clampAnswer ? "line-clamp-6" : ""}`}
          >
            {plain}
          </div>
          {showAnswerToggle && (
            <button
              type="button"
              onClick={() => setAnswerExpanded((v) => !v)}
              className="mt-2 cursor-pointer text-[11px] font-semibold text-primary hover:underline"
            >
              {answerExpanded ? "收起回答" : "展开全部回答"}
            </button>
          )}
        </div>
      )}
      {showResult && envelope ? (
        <MessageResultCard envelope={envelope} flush={floating} />
      ) : null}
    </div>
  );
}

function stripMd(s: string) {
  return s.replace(/[#*_`]/g, "").replace(/\n{3,}/g, "\n\n").trim();
}

function formatRelativeTime(iso?: string, _tick = 0): string {
  if (!iso) return "刚刚";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "刚刚";
  const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diffSec < 45) return "刚刚";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`;
  if (diffSec < 86400 * 7) return `${Math.floor(diffSec / 86400)} 天前`;
  return formatAbsoluteTime(iso);
}

function formatAbsoluteTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
