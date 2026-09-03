import { Navigate } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { fetchCurrentUser } from "../api";
import { useAuthStore } from "../authStore";

export function RequireAdmin({ children }: { children: ReactNode }) {
  const hydrated = useAuthStore((state) => state.hydrated);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    if (!hydrated) return;
    if (!isAuthenticated()) {
      setChecking(false);
      return;
    }
    let alive = true;
    void fetchCurrentUser()
      .then((user) => {
        if (!alive) return;
        setAllowed(user.roles.includes("admin") || user.perms.some((perm) => perm.startsWith("adm:")));
      })
      .catch(() => {
        if (alive) setAllowed(false);
      })
      .finally(() => {
        if (alive) setChecking(false);
      });
    return () => { alive = false; };
  }, [hydrated, isAuthenticated]);

  if (!hydrated) return <div className="flex h-full items-center justify-center text-sm text-muted-fg">加载中…</div>;
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  if (checking) return <div className="flex h-full items-center justify-center text-sm text-muted-fg">管理员权限校验中…</div>;
  if (!allowed) return <Navigate to="/workbench/input" replace />;
  return <>{children}</>;
}
