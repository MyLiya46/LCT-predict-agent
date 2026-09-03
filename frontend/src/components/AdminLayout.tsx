import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { ChartLine, Database, GearSix, ListChecks, SignOut, Sliders, UsersThree, Wrench } from "@phosphor-icons/react";
import { useAuthStore } from "../authStore";

const links = [
  ["/admin/users", "用户", UsersThree],
  ["/admin/tools", "工具", Wrench],
  ["/admin/datasources", "数据源", Database],
  ["/admin/llm", "LLM", Sliders],
  ["/admin/audits", "审计与追溯", ListChecks],
  ["/admin/config", "系统配置", GearSix],
] as const;

export function AdminLayout() {
  const navigate = useNavigate();
  const email = useAuthStore((state) => state.email);
  const oa = useAuthStore((state) => state.oa);
  const logout = useAuthStore((state) => state.logout);
  const onLogout = () => { logout(); navigate("/login", { replace: true }); };
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-5 shadow-sm">
        <div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-white"><ChartLine size={20} weight="bold" /></div><div><p className="font-semibold">预测智能体 · 管理端</p><p className="text-xs text-muted-fg">用户、工具与运行配置</p></div></div>
        <div className="flex items-center gap-3 text-sm"><span className="hidden text-muted-fg sm:inline">{email || oa || "未登录"}</span><button type="button" onClick={onLogout} className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-muted-fg hover:bg-muted hover:text-foreground"><SignOut size={16} />退出</button></div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 border-r border-border bg-card p-3">
          <nav className="space-y-1" aria-label="管理端导航">
            {links.map(([to, label, Icon]) => <NavLink key={to} to={to} className={({ isActive }) => `flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm transition ${isActive ? "bg-primary/10 font-medium text-primary" : "text-muted-fg hover:bg-muted hover:text-foreground"}`}><Icon size={18} />{label}</NavLink>)}
          </nav>
        </aside>
        <main className="min-h-0 min-w-0 flex-1"><Outlet /></main>
      </div>
    </div>
  );
}
