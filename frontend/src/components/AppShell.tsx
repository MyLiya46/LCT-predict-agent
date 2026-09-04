import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChartLine,
  Code,
  PlugsConnected,
  SignOut,
  User,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { SidebarNav } from "./SidebarNav";
import { WorkbenchKeepAlive } from "./WorkbenchKeepAlive";
import { useAppStore } from "../store";
import { useAuthStore } from "../authStore";

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const checkAgent = useAppStore((s) => s.checkAgent);
  const refreshSessions = useAppStore((s) => s.refreshSessions);
  const mcpOk = useAppStore((s) => s.mcpOk);
  const mcpMode = useAppStore((s) => s.mcpMode);
  const oa = useAuthStore((s) => s.oa);
  const email = useAuthStore((s) => s.email);
  const logout = useAuthStore((s) => s.logout);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const isChat = location.pathname.startsWith("/chat");
  const statusLabel = mcpMode === "provider" ? "Chat provider" : mcpMode === "live" ? "Agent live" : "Agent";

  useEffect(() => {
    void checkAgent();
    void refreshSessions();
  }, [checkAgent, refreshSessions]);

  useEffect(() => {
    if (isChat) return;
    const id = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 50);
    return () => window.clearTimeout(id);
  }, [isChat, location.pathname]);

  const onLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex h-full flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-4 shadow-sm md:px-5">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-white text-foreground md:hidden"
            aria-label="打开菜单"
            onClick={() => setSidebarOpen(true)}
          >
            <span className="text-lg leading-none">☰</span>
          </button>
          <Link to="/workbench/input" className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-white">
              <ChartLine size={20} weight="bold" aria-hidden />
            </div>
            <div className="hidden sm:block">
              <h1 className="text-base font-semibold tracking-tight text-foreground">预测智能体</h1>
              <p className="text-xs text-muted-fg">家电销售预测 · 归因 · What-if</p>
            </div>
          </Link>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-fg sm:gap-3">
          <NavLink
            to="/api"
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-2.5 py-1 text-primary transition hover:bg-muted"
          >
            <Code size={14} aria-hidden />
            <span className="hidden sm:inline">API 测试</span>
          </NavLink>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${
              mcpOk ? "bg-emerald-50 text-accent" : "bg-rose-50 text-destructive"
            }`}
            title="聊天服务连接状态"
          >
            <PlugsConnected size={14} aria-hidden />
            {statusLabel}
            {mcpOk === null ? " · 检测中" : mcpOk ? " · 已连接" : " · 异常"}
          </span>
          <span
            className="hidden items-center gap-1.5 rounded-full border border-border bg-white px-2.5 py-1 font-medium text-foreground sm:inline-flex"
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
            <span className="hidden sm:inline">退出</span>
          </button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1">
        {sidebarOpen && (
          <button
            type="button"
            className="absolute inset-0 z-20 bg-slate-900/35 md:hidden"
            aria-label="关闭菜单"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <aside
          className={`absolute inset-y-0 left-0 z-30 w-[248px] border-r border-border bg-card transition-transform md:static md:translate-x-0 ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <SidebarNav onNavigate={() => setSidebarOpen(false)} />
        </aside>
        <main className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
          <div
            className={isChat ? "hidden h-full min-h-0" : "h-full min-h-0"}
            aria-hidden={isChat}
          >
            <WorkbenchKeepAlive />
          </div>
          <div className={isChat ? "h-full min-h-0 overflow-hidden bg-background" : "hidden"}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
