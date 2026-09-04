import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ChartLine, SignIn } from "@phosphor-icons/react";
import { useAuthStore } from "../authStore";

type LoginMode = "oa" | "email";
type AuthView = "login" | "register";

export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const loginEmail = useAuthStore((s) => s.loginEmail);
  const register = useAuthStore((s) => s.register);
  const [view, setView] = useState<AuthView>("login");
  const [mode, setMode] = useState<LoginMode>("oa");
  const [oa, setOa] = useState("");
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const switchMode = (nextMode: LoginMode) => {
    setView("login");
    setMode(nextMode);
    setError(null);
    setNotice(null);
    setLoading(false);
  };

  const switchView = (nextView: AuthView) => {
    setView(nextView);
    setError(null);
    setNotice(null);
    setLoading(false);
    if (nextView === "register") setMode("email");
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (loading) return;
    const normalizedOa = oa.trim();
    const normalizedEmail = email.trim();
    if (view === "login" && mode === "oa" && !normalizedOa) return;
    if (view === "login" && mode === "email" && (!normalizedEmail || !password)) return;
    if (view === "register" && (!normalizedEmail || !password || password !== confirmPassword)) {
      setError(password !== confirmPassword ? "两次输入的密码不一致" : "请填写完整注册信息");
      return;
    }
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      if (view === "register") {
        await register(normalizedEmail, password, nickname);
        setView("login");
        setMode("email");
        setPassword("");
        setConfirmPassword("");
        setNotice("注册成功，请使用账号登录");
        return;
      } else if (mode === "oa") {
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

        {view === "login" ? (
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
        ) : (
          <div className="mb-5 rounded-lg bg-muted px-3 py-2 text-sm font-medium text-primary">注册账号</div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          {view === "register" ? (
            <>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-fg">邮箱</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  autoFocus
                  autoComplete="email"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-fg">昵称（可选）</span>
                <input
                  value={nickname}
                  onChange={(e) => setNickname(e.target.value)}
                  autoComplete="nickname"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-fg">密码</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder="至少10位，含大小写字母和数字"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted-fg">确认密码</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                />
              </label>
            </>
          ) : mode === "oa" ? (
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
          {notice && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-accent">
              {notice}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || (
              view === "register"
                ? !email.trim() || !password || !confirmPassword
                : mode === "oa"
                  ? !oa.trim()
                  : !email.trim() || !password
            )}
            className="inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <SignIn size={16} weight="bold" />
            {loading ? (view === "register" ? "注册中…" : "登录中…") : view === "register" ? "注册账号" : "进入系统"}
          </button>
        </form>

        <div className="mt-4 flex items-center justify-between text-[11px] text-muted-fg">
          <span>{view === "login" ? "OA 登录和账号登录使用独立入口" : "注册后即可使用账号登录"}</span>
          <button
            type="button"
            onClick={() => switchView(view === "login" ? "register" : "login")}
            className="cursor-pointer font-medium text-primary hover:underline"
          >
            {view === "login" ? "注册账号" : "返回登录"}
          </button>
        </div>
      </div>
    </div>
  );
}
