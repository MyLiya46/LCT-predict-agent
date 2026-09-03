import { Navigate, Route, Routes } from "react-router-dom";
import { useEffect, type ReactNode } from "react";
import { LoginPage } from "./pages/LoginPage";
import { ApiLabPage } from "./pages/ApiLabPage";
import ChatPage from "./pages/ChatPage";
import { AppShell } from "./components/AppShell";
import { useAuthStore } from "./authStore";
import { RequireAdmin } from "./components/RequireAdmin";
import { AdminLayout } from "./components/AdminLayout";
import { UsersPage } from "./pages/admin/UsersPage";
import { ToolsPage } from "./pages/admin/ToolsPage";
import { DatasourcesPage } from "./pages/admin/DatasourcesPage";
import { LlmPage } from "./pages/admin/LlmPage";
import { AuditsPage } from "./pages/admin/AuditsPage";
import { ConfigPage } from "./pages/admin/ConfigPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const hydrated = useAuthStore((s) => s.hydrated);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  if (!hydrated) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-fg">加载中…</div>
    );
  }
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const hydrate = useAuthStore((s) => s.hydrate);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/workbench/input" replace />} />
        {/* 工作台页面由 AppShell 内 KeepAlive 渲染，避免栏目切换卸载重载 */}
        <Route path="workbench/*" element={<></>} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="chat/:sessionId" element={<ChatPage />} />
      </Route>
      <Route
        path="/api"
        element={
          <RequireAuth>
            <ApiLabPage />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/*"
        element={
          <RequireAdmin>
            <AdminLayout />
          </RequireAdmin>
        }
      >
        <Route index element={<Navigate to="/admin/users" replace />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="datasources" element={<DatasourcesPage />} />
        <Route path="llm" element={<LlmPage />} />
        <Route path="audits" element={<AuditsPage />} />
        <Route path="config" element={<ConfigPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/workbench/input" replace />} />
    </Routes>
  );
}
