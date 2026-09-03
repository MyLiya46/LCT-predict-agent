import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ChartLine,
  CirclesThreePlus,
  Code,
  Database,
  PlugsConnected,
  SignOut,
  User,
} from "@phosphor-icons/react";
import { ChatPanel } from "../components/ChatPanel";
import { InsightPanel } from "../components/InsightPanel";
import { ChartPanel } from "../components/ChartPanel";
import { TablePanel } from "../components/TablePanel";
import { useAppStore } from "../store";
import { useAuthStore } from "../authStore";

const CHAT_WIDTH_KEY = "forecast-agent-chat-width";
const LG_MQ = "(min-width: 1024px)";

function clampChatWidth(px: number, viewportW: number) {
  const min = viewportW / 5;
  const max = viewportW / 3;
  return Math.min(max, Math.max(min, px));
}

function initialChatWidth() {
  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  try {
    const saved = Number(localStorage.getItem(CHAT_WIDTH_KEY));
    if (Number.isFinite(saved) && saved > 0) return clampChatWidth(saved, vw);
  } catch {
    /* ignore */
  }
  return clampChatWidth(vw * 0.28, vw);
}

export default function WorkbenchPage() {
  const navigate = useNavigate();
  const checkAgent = useAppStore((s) => s.checkAgent);
  const refreshSessions = useAppStore((s) => s.refreshSessions);
  const mcpOk = useAppStore((s) => s.mcpOk);
  const mcpMode = useAppStore((s) => s.mcpMode);
  const envelope = useAppStore((s) => s.envelope);
  const oa = useAuthStore((s) => s.oa);
  const email = useAuthStore((s) => s.email);
  const logout = useAuthStore((s) => s.logout);

  const [chatWidth, setChatWidth] = useState(initialChatWidth);
  const [isLg, setIsLg] = useState(
    () => typeof window !== "undefined" && window.matchMedia(LG_MQ).matches,
  );
  const [dragging, setDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartW = useRef(0);

  useEffect(() => {
    void checkAgent();
    void refreshSessions();
  }, [checkAgent, refreshSessions]);

  useEffect(() => {
    const mq = window.matchMedia(LG_MQ);
    const onChange = () => setIsLg(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const onResize = () => {
      setChatWidth((w) => clampChatWidth(w, window.innerWidth));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const next = clampChatWidth(
        dragStartW.current + (e.clientX - dragStartX.current),
        window.innerWidth,
      );
      setChatWidth(next);
    };
    const onUp = () => {
      setDragging(false);
      setChatWidth((w) => {
        try {
          localStorage.setItem(CHAT_WIDTH_KEY, String(Math.round(w)));
        } catch {
          /* ignore */
        }
        return w;
      });
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  const onDragStart = useCallback(
    (e: ReactMouseEvent) => {
      e.preventDefault();
      dragStartX.current = e.clientX;
      dragStartW.current = chatWidth;
      setDragging(true);
    },
    [chatWidth],
  );

  const onLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-white">
            <ChartLine size={20} weight="bold" aria-hidden />
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight text-foreground">预测智能体</h1>
            <p className="text-xs text-muted-fg">家电销售预测 · 归因 · What-if</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-fg">
          <Link
            to="/api"
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-2.5 py-1 text-primary transition hover:bg-muted"
          >
            <Code size={14} aria-hidden />
            API 测试
          </Link>
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <CirclesThreePlus size={14} aria-hidden />
            分析解读 → 图表 → 数据表
          </span>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${
              mcpOk ? "bg-emerald-50 text-accent" : "bg-rose-50 text-destructive"
            }`}
            title="Agent Chat API 连接状态"
          >
            <PlugsConnected size={14} aria-hidden />
            Agent {mcpMode}
            {mcpOk === null ? " · 检测中" : mcpOk ? " · 已连接" : " · 异常"}
          </span>
          <span
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-2.5 py-1 font-medium text-foreground"
            title="当前登录账号"
          >
            <User size={14} className="text-primary" aria-hidden />
            {oa || email || "未登录"}
          </span>
          <button
            type="button"
            onClick={onLogout}
            className="inline-flex cursor-pointer items-center gap-1 rounded-full px-2 py-1 text-muted-fg transition hover:bg-muted hover:text-foreground"
            aria-label="退出登录"
          >
            <SignOut size={14} />
            退出
          </button>
        </div>
      </header>

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside
          className="relative min-h-[42vh] w-full shrink-0 border-b border-border bg-card lg:min-h-0 lg:border-b-0 lg:border-r"
          style={isLg ? { width: chatWidth } : undefined}
        >
          <ChatPanel />
          {isLg && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="拖动调整对话区宽度"
              onMouseDown={onDragStart}
              className={`absolute -right-1 top-0 z-20 h-full w-2 cursor-col-resize ${
                dragging ? "bg-primary/20" : "hover:bg-primary/10"
              }`}
            >
              <span className="absolute left-1/2 top-1/2 h-8 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-border" />
            </div>
          )}
        </aside>

        <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-auto p-4">
          {!envelope ? (
            <EmptyState />
          ) : (
            <>
              <InsightPanel />
              <ChartPanel />
              <TablePanel />
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-8 py-16 text-center shadow-panel">
      <Database size={40} className="mb-4 text-primary/70" aria-hidden />
      <h2 className="mb-2 text-lg font-semibold">发起一次对话</h2>
      <p className="max-w-md text-sm leading-relaxed text-muted-fg">
        在左侧对话框输出您的问题，或点击快捷对话主题，结果将在工作台区域展示。
      </p>
    </div>
  );
}
