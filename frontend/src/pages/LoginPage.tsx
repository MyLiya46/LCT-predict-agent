import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ChartLine, SignIn } from "@phosphor-icons/react";
import { useAuthStore } from "../authStore";

type LoginMode = "oa" | "email";

export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const loginEmail = useAuthStore((s) => s.loginEmail);
  const [mode, setMode] = useState<LoginMode>("oa");
  const [oa, setOa] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const switchMode = (nextMode: LoginMode) => {
    setMode(nextMode);
    setError(null);
    setLoading(false);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (loading) return;
    const normalizedOa = oa.trim();
    const normalizedEmail = email.trim();
    if (mode === "oa" && !normalizedOa) return;
    if (mode === "email" && (!normalizedEmail || !password)) return;
    setLoading(true);
    setError(null);
    try {
      if (mode === "oa") {
        await login(normalizedOa);
      } else {
        await loginEmail(normalizedEmail, password);
      }
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-[var(--color-background)] px-4">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-white">
            <ChartLine size={22} weight="bold" aria-hidden />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">预测智能体</h1>
            <p className="text-xs text-muted-fg">请选择登录方式进入系统</p>
          </div>
        </div>

        <div className="mb-5 grid grid-cols-2 rounded-lg bg-muted p-1" role="tablist" aria-label="登录方式">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "oa"}
            onClick={() => switchMode("oa")}
            className={`rounded-md px-3 py-2 text-sm font-medium transition ${
              mode === "oa" ? "bg-white text-primary shadow-sm" : "text-muted-fg"
            }`}
          >
            OA 登录
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "email"}
            onClick={() => switchMode("email")}
            className={`rounded-md px-3 py-2 text-sm font-medium transition ${
              mode === "email" ? "bg-white text-primary shadow-sm" : "text-muted-fg"
            }`}
          >
            账号登录
          </button>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          {mode === "oa" ? (
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted-fg">OA 账号</span>
              <input
                value={oa}
                onChange={(e) => setOa(e.target.value)}
                placeholder="例如 jie32.guo"
                autoFocus
                autoComplete="username"
                className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
              />
            </label>
          ) : (
            <>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-fg">邮箱</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  autoFocus
                  autoComplete="username"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-fg">密码</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                />
              </label>
            </>
          )}

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || (mode === "oa" ? !oa.trim() : !email.trim() || !password)}
            className="inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <SignIn size={16} weight="bold" />
            {loading ? "登录中…" : "进入系统"}
          </button>
        </form>

        <p className="mt-4 text-[11px] leading-relaxed text-muted-fg">
          OA 登录和账号登录使用独立的认证入口，工作台请求会自动使用当前会话。
        </p>
      </div>
    </div>
  );
}
