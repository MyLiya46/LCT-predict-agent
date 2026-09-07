import type { AgentResultEnvelope, ChatParams, SessionSummary } from "./types";

const BASE = "";

export type OaLoginResponse = {
  ok?: boolean;
  oa: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  oauth_access_token: string;
  oauth_token_type: string;
  oauth_expires_in: number;
};

export type BackupTokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

export type ChatAuth = {
  oa?: string | null;
  backupAccessToken: string;
  oauthAccessToken?: string | null;
};

const PUBLIC_PATHS = new Set([
  "/api/auth/login",
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/refresh",
  "/api/health/agent",
]);

export function readBackupToken(): string | null {
  try {
    const raw = localStorage.getItem("forecast-agent-auth");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { accessToken?: unknown };
    return typeof parsed.accessToken === "string" && parsed.accessToken
      ? parsed.accessToken
      : null;
  } catch {
    return null;
  }
}

function isPublicPath(url: string) {
  const path = url.split("?", 1)[0];
  return PUBLIC_PATHS.has(path);
}

function readableErrorMessage(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (!value || typeof value !== "object") return null;
  const payload = value as { message?: unknown; detail?: unknown; data?: unknown };
  if (typeof payload.message === "string" && payload.message.trim()) return payload.message;
  if (typeof payload.detail === "string" && payload.detail.trim()) return payload.detail;
  if (payload.detail != null) return JSON.stringify(payload.detail);
  if (payload.data && typeof payload.data === "object") return readableErrorMessage(payload.data);
  return null;
}

async function errorFromResponse(res: Response): Promise<Error> {
  const text = await res.text();
  let message = text || res.statusText;
  try {
    const parsed = JSON.parse(text) as unknown;
    message = readableErrorMessage(parsed) || message;
  } catch {
    /* keep the raw response text */
  }
  if (res.status === 404 && /not found/i.test(message)) {
    return new Error("登录接口不存在（404）。请重启后端 uvicorn 后重试。");
  }
  return new Error(message);
}

function requestHeaders(init: RequestInit | undefined, protectedRequest: boolean, token?: string | null) {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (protectedRequest) {
    const backupToken = token ?? readBackupToken();
    if (backupToken) headers.set("Authorization", `Bearer ${backupToken}`);
    else headers.delete("Authorization");
  } else {
    headers.delete("Authorization");
  }
  return headers;
}

let refreshPromise: Promise<string | null> | null = null;

export async function refreshBackupTokenOnce(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const raw = localStorage.getItem("forecast-agent-auth");
      if (!raw) return null;
      const current = JSON.parse(raw) as Record<string, unknown>;
      const refreshToken = typeof current.refreshToken === "string" ? current.refreshToken : "";
      if (!refreshToken) return null;
      const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return null;
      const payload = (await res.json()) as { data?: BackupTokenResponse } & BackupTokenResponse;
      const data = payload.data || payload;
      if (!data.access_token || !data.refresh_token || !Number.isFinite(data.expires_in) || data.expires_in <= 0) {
        return null;
      }
      const next = {
        mode: current.mode === "email" ? "email" : "oa",
        oa: typeof current.oa === "string" ? current.oa : null,
        email: typeof current.email === "string" ? current.email : null,
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        tokenType: data.token_type || "bearer",
        expiresAt: Date.now() + data.expires_in * 1000,
        oauthAccessToken: typeof current.oauthAccessToken === "string" ? current.oauthAccessToken : null,
        oauthTokenType: typeof current.oauthTokenType === "string" ? current.oauthTokenType : null,
        oauthExpiresAt: typeof current.oauthExpiresAt === "number" ? current.oauthExpiresAt : 0,
      };
      localStorage.setItem("forecast-agent-auth", JSON.stringify(next));
      window.dispatchEvent(new Event("forecast-agent-auth-updated"));
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const protectedRequest = !isPublicPath(url);
  const request = (token?: string | null) => fetch(`${BASE}${url}`, {
    ...init,
    headers: requestHeaders(init, protectedRequest, token),
  });
  let res = await request();
  if (!res.ok) {
    if (protectedRequest && res.status === 401) {
      const refreshedToken = await refreshBackupTokenOnce();
      if (refreshedToken) {
        res = await request(refreshedToken);
      }
    }
    if (!res.ok) throw await errorFromResponse(res);
  }
  return res.json() as Promise<T>;
}

export async function loginWithOa(oa: string): Promise<OaLoginResponse> {
  return json<OaLoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ oa }),
  });
}

export async function loginWithEmail(email: string, password: string): Promise<BackupTokenResponse> {
  const response = await json<{ data: BackupTokenResponse }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return response.data;
}

export async function registerWithEmail(
  email: string,
  password: string,
  nickname: string,
): Promise<{ user_id: string; email: string }> {
  const response = await json<{ data: { user_id: string; email: string } }>('/api/v1/auth/register', {
    method: "POST",
    body: JSON.stringify({ email, password, nickname }),
  });
  return response.data;
}

export async function refreshWithToken(refreshToken: string): Promise<BackupTokenResponse> {
  const response = await json<{ data: BackupTokenResponse }>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  return response.data;
}

export async function logoutWithToken(accessToken: string, refreshToken: string): Promise<void> {
  try {
    await fetch(`${BASE}/api/v1/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
        "X-Refresh-Token": refreshToken,
      },
    });
  } catch {
    /* best effort: local logout must not be blocked by a network failure */
  }
}

export type AdminUser = {
  id: string;
  email: string;
  nickname?: string | null;
  status: string;
  roles: string[];
  created_at?: string | null;
};

export type AdminTool = {
  id: string;
  name: string;
  description?: string;
  status?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  execution?: Record<string, unknown>;
  scenario_id?: string | null;
};

export type AdminDatasource = {
  id: string;
  name: string;
  type?: string;
  base_url: string;
  whitelist?: string[];
  enabled: boolean;
};

export type AdminLlmProvider = {
  id: string;
  name: string;
  vendor?: string;
  base_url: string;
  models: string[];
  default_model: string;
  api_key_encrypted?: string;
  status?: string;
  fallback_provider_id?: string | null;
};

export type AdminList<T> = { items: T[]; next_cursor?: string | null; cursor?: string | null };
export type AdminSession = Record<string, unknown> & { id?: string; title?: string; status?: string };
export type AdminMessage = Record<string, unknown> & { id?: string; content?: string; status?: string };
export type AdminTrace = Record<string, unknown> & { trace_id?: string; tool_name?: string; error_code?: string };
export type AdminAudit = Record<string, unknown> & { id?: string; action?: string; actor_email?: string };

export type AdminConfig = Record<string, unknown>;

function adminPayload<T>(response: unknown): T {
  if (!response || typeof response !== "object") return response as T;
  const body = response as { code?: unknown; message?: unknown; data?: unknown };
  if (body.code !== undefined && body.code !== "0") {
    throw new Error(typeof body.message === "string" ? body.message : "管理端请求失败");
  }
  return body.data as T;
}

/** 管理端统一响应封装；只从当前会话读取短期 backup access token。 */
export async function adminJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await json<unknown>(url, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      "Content-Type": "application/json",
    },
  });
  return adminPayload<T>(response);
}

export async function fetchCurrentUser() {
  return adminJson<{
    id: string;
    email: string;
    nickname?: string;
    roles: string[];
    perms: string[];
  }>("/api/v1/auth/me");
}

function queryString(filters: Record<string, string | number | undefined | null>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") params.set(key, String(value));
  });
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function adminListUsers(q = "", role = "", status = "", limit = 100) {
  return adminJson<AdminList<AdminUser>>(`/api/v1/admin/users${queryString({ q, role, status, limit })}`);
}
export function adminCreateUser(body: { email: string; nickname: string; initial_password: string; role: string }) {
  return adminJson<{ id: string; email: string }>("/api/v1/admin/users", { method: "POST", body: JSON.stringify(body) });
}
export function adminPatchUser(id: string, body: { nickname?: string; role?: string; status?: string }) {
  return adminJson<{ id: string }>(`/api/v1/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function adminResetPassword(id: string, new_password: string) {
  return adminJson<{ ok: boolean }>(`/api/v1/admin/users/${encodeURIComponent(id)}/reset-password`, { method: "POST", body: JSON.stringify({ new_password }) });
}

export function adminListTools() { return adminJson<AdminTool[]>("/api/v1/admin/tools"); }
export function adminCreateTool(body: { name: string; description: string; input_schema: Record<string, unknown>; output_schema: Record<string, unknown>; execution: Record<string, unknown>; scenario_id?: string }) {
  return adminJson<{ id: string; name: string }>("/api/v1/admin/tools", { method: "POST", body: JSON.stringify(body) });
}
export function adminPatchTool(id: string, body: { status?: string; description?: string; execution?: Record<string, unknown> }) {
  return adminJson<{ id: string; status?: string }>(`/api/v1/admin/tools/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function adminDeleteTool(id: string) { return adminJson<{ ok: boolean }>(`/api/v1/admin/tools/${encodeURIComponent(id)}`, { method: "DELETE" }); }
export function adminTestTool(id: string) { return adminJson<Record<string, { ok: boolean; detail?: string }>>(`/api/v1/admin/tools/${encodeURIComponent(id)}/test`, { method: "POST" }); }

export function adminListDatasources() { return adminJson<AdminDatasource[]>("/api/v1/admin/datasources"); }
export function adminCreateDatasource(body: { name: string; type: string; base_url: string; credential: string; whitelist: string[]; enabled: boolean }) {
  return adminJson<{ id: string; name: string }>("/api/v1/admin/datasources", { method: "POST", body: JSON.stringify(body) });
}
export function adminPatchDatasource(id: string, body: { name?: string; base_url?: string; enabled?: boolean }) {
  return adminJson<{ id: string }>(`/api/v1/admin/datasources/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function adminTestDatasource(id: string) { return adminJson<{ ok?: boolean; detail?: string }>(`/api/v1/admin/datasources/${encodeURIComponent(id)}/test`, { method: "POST" }); }

export function adminListLlm() { return adminJson<AdminLlmProvider[]>("/api/v1/admin/llm"); }
export function adminCreateLlm(body: { name: string; vendor: string; base_url: string; api_key: string; models: string[]; default_model: string; fallback_provider_id?: string }) {
  return adminJson<{ id: string; name: string }>("/api/v1/admin/llm", { method: "POST", body: JSON.stringify(body) });
}
export function adminPatchLlm(id: string, body: { name?: string; base_url?: string; api_key?: string; models?: string[]; default_model?: string; fallback_provider_id?: string }) {
  return adminJson<{ id: string }>(`/api/v1/admin/llm/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function adminDeleteLlm(id: string) { return adminJson<{ ok: boolean }>(`/api/v1/admin/llm/${encodeURIComponent(id)}`, { method: "DELETE" }); }
export function adminHealthLlm(id: string) { return adminJson<{ ok?: boolean; detail?: string }>(`/api/v1/admin/llm/${encodeURIComponent(id)}/health`, { method: "POST" }); }
export function adminDefaultLlm() { return adminJson<AdminLlmProvider | null>("/api/v1/admin/llm/default"); }

export function adminListSessions(filters: { q?: string; status?: string; owner_email?: string; limit?: number } = {}) {
  return adminJson<AdminList<AdminSession>>(`/api/v1/admin/sessions${queryString(filters)}`);
}
export function adminListMessages(filters: { q?: string; status?: string; owner_email?: string; limit?: number } = {}) {
  return adminJson<AdminList<AdminMessage>>(`/api/v1/admin/messages${queryString(filters)}`);
}
export function adminListTraces(filters: { trace_id?: string; tool_name?: string; error_code?: string; actor_email?: string } = {}) {
  return adminJson<AdminList<AdminTrace>>(`/api/v1/admin/traces${queryString(filters)}`);
}
export function adminTraceDetail(trace_id: string) { return adminJson<{ trace_id: string; events: Array<Record<string, unknown>> }>(`/api/v1/admin/traces/${encodeURIComponent(trace_id)}`); }
export function adminListAudits(filters: { type?: string; actor?: string; target?: string; limit?: number } = {}) {
  return adminJson<AdminList<AdminAudit>>(`/api/v1/admin/audits${queryString(filters)}`);
}
export function adminAuditDetail(id: string) { return adminJson<AdminAudit>(`/api/v1/admin/audits/${encodeURIComponent(id)}`); }

export function adminGetConfig() { return adminJson<AdminConfig>("/api/v1/admin/config"); }
export function adminPatchConfig(key: string, value: unknown) {
  return adminJson<{ key: string; value: unknown }>("/api/v1/admin/config", { method: "PATCH", body: JSON.stringify({ key, value }) });
}

export async function fetchAgentHealth() {
  return json<{
    ok: boolean;
    mode?: string;
    configured_mode?: string;
    error?: string;
    provider?: string;
    url?: string;
  }>("/api/health/agent");
}

/** @deprecated use fetchAgentHealth */
export async function fetchMcpHealth() {
  return fetchAgentHealth();
}

export async function fetchSessions() {
  return json<SessionSummary[]>("/api/sessions");
}

export async function updateSession(
  id: string,
  patch: { title?: string; pinned?: boolean },
) {
  return json<SessionSummary>(`/api/sessions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteSession(id: string): Promise<{ ok: boolean }> {
  return json<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function fetchSession(id: string) {
  return json<{
    id: string;
    title: string;
    messages: {
      id: string;
      role: string;
      content: string;
      result_envelope?: AgentResultEnvelope | null;
      created_at: string;
    }[];
  }>(`/api/sessions/${id}`);
}

function chatBody(message: string, sessionId: string | null, params: ChatParams, auth: ChatAuth) {
  return {
    message,
    session_id: sessionId,
    params,
    ...(auth.oa ? { oa: auth.oa } : {}),
    ...(auth.oauthAccessToken ? { access_token: auth.oauthAccessToken } : {}),
  };
}

export async function sendChat(
  message: string,
  sessionId: string | null,
  params: ChatParams,
  auth: ChatAuth,
) {
  return json<{
    session_id: string;
    message_id: string;
    reply: string;
    envelope: AgentResultEnvelope;
  }>("/api/chat", {
    method: "POST",
    headers: { Authorization: `Bearer ${auth.backupAccessToken}` },
    body: JSON.stringify(chatBody(message, sessionId, params, auth)),
  });
}

export type StreamStatus = {
  stage?: string;
  intent?: string;
  text?: string;
  steps?: string[];
};

export type ChatResultPayload = {
  session_id: string;
  message_id: string;
  reply: string;
  envelope: AgentResultEnvelope;
  update_workspace?: boolean;
  steps?: string[];
};

/** 消费 /api/chat/stream，边收边回调处理过程 */
export async function sendChatStream(
  message: string,
  sessionId: string | null,
  params: ChatParams,
  onStatus: (status: StreamStatus) => void,
  onDelta: (text: string) => void,
  auth: ChatAuth,
): Promise<ChatResultPayload> {
  const requestInit: RequestInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${auth.backupAccessToken}`,
    },
    body: JSON.stringify(chatBody(message, sessionId, params, auth)),
  };
  let res = await fetch(`${BASE}/api/chat/stream`, requestInit);
  if (!res.ok) {
    if (res.status === 401) {
      const refreshedToken = await refreshBackupTokenOnce();
      if (refreshedToken) {
        res = await fetch(`${BASE}/api/chat/stream`, {
          ...requestInit,
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${refreshedToken}`,
          },
        });
      }
    }
    if (!res.ok) throw await errorFromResponse(res);
  }
  if (!res.body) {
    throw new Error("浏览器不支持流式响应");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ChatResultPayload | null = null;

  const handleBlock = (block: string) => {
    const lines = block.split(/\r?\n/);
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    if (!dataLines.length) return;
    try {
      const data = JSON.parse(dataLines.join("\n")) as StreamStatus & ChatResultPayload & { ok?: boolean };
      if (eventName === "status") {
        onStatus(data);
      } else if (eventName === "delta") {
        if (typeof data.text === "string" && data.text) onDelta(data.text);
      } else if (eventName === "result") {
        result = {
          session_id: data.session_id,
          message_id: data.message_id,
          reply: data.reply,
          envelope: data.envelope,
          update_workspace: data.update_workspace,
          steps: data.steps,
        };
      }
    } catch {
      /* ignore malformed chunk */
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() || "";
    for (const part of parts) {
      if (part.trim()) handleBlock(part.trim());
    }
  }
  if (buffer.trim()) handleBlock(buffer.trim());

  if (!result) {
    throw new Error("流式响应未返回结果");
  }
  return result;
}

export async function fetchProducts() {
  return json<{ id: string; sku: string; name: string; category: string; brand: string }[]>(
    "/api/products",
  );
}

export async function fetchAgentProbeTemplate(stream = false) {
  return json<{
    url: string;
    mode: string;
    headers: Record<string, string>;
    body: Record<string, unknown>;
  }>(`/api/agent/probe/template?stream=${stream ? "true" : "false"}`);
}

export async function probeAgent(payload: {
  url?: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}) {
  return json<{
    ok: boolean;
    latency_ms?: number;
    status_code?: number;
    response_mode?: string;
    request?: unknown;
    response?: unknown;
    events?: unknown[];
    answer?: string | null;
    error?: string;
  }>("/api/agent/probe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type WorkbenchFilterDef = { key: string; label: string };

export type WorkbenchDatasetMeta = {
  key: string;
  title: string;
  group: string;
  filters: WorkbenchFilterDef[];
  column_priority?: string[];
  row_count: number;
};

export type WorkbenchTableResponse = {
  dataset: string;
  title: string;
  columns: { key: string; title: string }[];
  rows: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
  filters: WorkbenchFilterDef[];
  /** @deprecated 请使用 fetchWorkbenchFilterOptions */
  filter_options?: Record<string, string[]>;
};

export type WorkbenchFilterOptionsResponse = {
  dataset: string;
  filters: WorkbenchFilterDef[];
  filter_options: Record<string, string[]>;
};

const filterOptionsCache = new Map<string, WorkbenchFilterOptionsResponse>();

export function invalidateWorkbenchFilterOptionsCache(dataset?: string) {
  if (!dataset) {
    filterOptionsCache.clear();
    return;
  }
  for (const key of [...filterOptionsCache.keys()]) {
    if (key.startsWith(`${dataset}|`)) filterOptionsCache.delete(key);
  }
}

export async function fetchWorkbenchFilterOptions(
  dataset: string,
  opts?: {
    refresh?: boolean;
    essential?: boolean;
    category?: string;
    version?: string;
  },
): Promise<WorkbenchFilterOptionsResponse> {
  const cacheKey = [
    dataset,
    opts?.essential ? "essential" : "full",
    opts?.category || "",
    opts?.version || "",
  ].join("|");
  if (!opts?.refresh && filterOptionsCache.has(cacheKey)) {
    return filterOptionsCache.get(cacheKey)!;
  }
  const qs = new URLSearchParams();
  if (opts?.essential) qs.set("essential", "1");
  if (opts?.category) qs.set("category", opts.category);
  if (opts?.version) qs.set("version", opts.version);
  const q = qs.toString();
  const res = await json<WorkbenchFilterOptionsResponse>(
    `/api/workbench/filter-options/${encodeURIComponent(dataset)}${q ? `?${q}` : ""}`,
  );
  filterOptionsCache.set(cacheKey, res);
  return res;
}

export type WorkbenchChartSeries = {
  dataset: string;
  months: string[];
  quantity: number[];
  amount: number[];
};

export async function fetchWorkbenchDatasets() {
  return json<WorkbenchDatasetMeta[]>("/api/workbench/datasets");
}

export type StrategyKnowledgeResponse = {
  title: string;
  source: string;
  markdown: string;
};

export async function fetchStrategyKnowledge() {
  return json<StrategyKnowledgeResponse>("/api/workbench/knowledge/strategy");
}

export async function fetchWorkbenchTable(
  dataset: string,
  params: Record<string, string | number | undefined>,
) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    qs.set(k, String(v));
  });
  const q = qs.toString();
  return json<WorkbenchTableResponse>(
    `/api/workbench/tables/${encodeURIComponent(dataset)}${q ? `?${q}` : ""}`,
  );
}

export async function fetchWorkbenchChart(
  dataset: string,
  params: Record<string, string | number | undefined>,
) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    qs.set(k, String(v));
  });
  const q = qs.toString();
  return json<WorkbenchChartSeries>(
    `/api/workbench/charts/${encodeURIComponent(dataset)}${q ? `?${q}` : ""}`,
  );
}

export type CostDataUploadResult = {
  ok: boolean;
  dataset: string;
  upserted: number;
  skipped: number;
  updated_at: string;
};

export async function uploadCostData(file: File): Promise<CostDataUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/api/workbench/upload/cost_data`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed?.detail) throw new Error(parsed.detail);
    } catch (e) {
      if (e instanceof Error && e.message !== text) throw e;
    }
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<CostDataUploadResult>;
}

export type AttributionOptions = {
  category: string[];
  version: string[];
  status: string[];
};

export type AttributionSkuItem = {
  sku: string;
  channel_l1: string;
  channel_l3: string;
  status: string;
  series: string;
  y_pred: number;
  qty_lag1: number;
  period?: string;
  meta?: string;
};

export type AttributionSkuList = {
  category: string;
  version: string;
  period: string | null;
  months: string[];
  items: AttributionSkuItem[];
  total: number;
};

export type AttributionWaterfall = {
  xAxis: string[];
  placeholder: number[];
  values: number[];
  labels: string[];
  colors: string[];
  baseline: number;
  final: number;
};

export type AttributionTrend = {
  periods: string[];
  history: (number | string)[];
  forecast: (number | string)[];
  history_count: number;
  forecast_count: number;
  split_period: string | null;
  horizons: string[];
};

export type AttributionDetail = {
  ok: boolean;
  error?: string;
  sku: string;
  channel_l1: string;
  channel_l3: string;
  status: string;
  series: string;
  category: string;
  version: string;
  period: string | null;
  months: string[];
  meta: string;
  y_pred: number;
  qty_lag1: number;
  model?: string | null;
  method?: string | null;
  attribution_text: string;
  waterfall: AttributionWaterfall;
  type_impacts: { type: string; impact: number }[];
};

function toQuery(params: Record<string, string | number | undefined | null>) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    qs.set(k, String(v));
  });
  return qs.toString();
}

export async function fetchAttributionOptions() {
  return json<AttributionOptions>("/api/attribution/options");
}

export async function fetchAttributionSkus(
  params: Record<string, string | number | undefined>,
) {
  const q = toQuery(params);
  return json<AttributionSkuList>(`/api/attribution/skus${q ? `?${q}` : ""}`);
}

export async function fetchAttributionDetail(
  params: Record<string, string | number | undefined>,
) {
  const q = toQuery(params);
  return json<AttributionDetail>(`/api/attribution/detail${q ? `?${q}` : ""}`);
}

export async function fetchAttributionTrend(
  params: Record<string, string | number | undefined>,
) {
  const q = toQuery(params);
  return json<AttributionTrend>(`/api/attribution/trend${q ? `?${q}` : ""}`);
}

export type WhatIfDetail = {
  version?: string | null;
  month?: string | null;
  period?: string | null;
  forecast_period?: string | null;
  sku: string;
  channel?: string | null;
  channel_l3?: string | null;
  category?: string | null;
  forecast_qty: number;
  baseline_price: number | null;
  cost_price: number | null;
  baseline_qty?: number;
  plan_price?: number | null;
  baseline_amount?: number | null;
  sim_qty?: number;
  sim_price?: number | null;
  sim_amount?: number | null;
  sim_gross_profit?: number | null;
  price_status?: string;
  cost_status?: string;
  elasticity?: {
    coefficient: number | null;
    volatility_class: string;
    elasticity_class: string;
    ed: number;
    ed_source: string;
  };
};

export type WhatIfBaselineItem = {
  version?: string | null;
  sku: string;
  month?: string | null;
  channel?: string | null;
  channel_l3?: string | null;
  channels?: string[];
  category?: string | null;
  period?: string | null;
  forecast_period?: string | null;
  status?: string | null;
  series?: string | null;
  forecast_qty?: number;
  baseline_price?: number | null;
  cost_price?: number | null;
  plan_price?: number | null;
  baseline_qty: number;
  baseline_amount: number | null;
  sim_qty: number;
  sim_price?: number | null;
  sim_amount?: number | null;
  sim_gross_profit?: number | null;
  details?: WhatIfDetail[];
  price_coverage_qty?: number;
  cost_coverage_qty?: number;
  gross_profit?: number | null;
  gross_coverage_qty?: number;
  price_status?: string;
  cost_status?: string;
  gross_profit_status?: string;
  elasticity?: {
    coefficient: number | null;
    volatility_class: string;
    elasticity_class: string;
    ed: number;
    ed_source: string;
  };
};

export type WhatIfBaselineSummary = {
  baseline_qty: number;
  baseline_amount: number;
  months: string[];
  qty_series: number[];
  amount_series: number[];
  gross_profit?: number | null;
  gross_margin?: number | null;
  price_coverage_qty?: number;
  cost_coverage_qty?: number;
  gross_coverage_qty?: number;
  price_status?: string;
  cost_status?: string;
  gross_profit_status?: string;
  item_count?: number;
  visible_item_count?: number;
  detail_count?: number;
  inventory_turnover_days?: number | null;
  inventory_turnover_label?: string | null;
  inventory_turnover_status?: string;
  inventory_turnover_reason?: string | null;
};

export type WhatIfBaseline = {
  ok: boolean;
  error?: string;
  source?: string;
  category: string;
  version: string;
  period: string | null;
  months: string[];
  items: WhatIfBaselineItem[];
  summary: WhatIfBaselineSummary;
  total: number;
  elasticity_hits?: number;
};

export async function fetchWhatIfBaseline(
  params: Record<string, string | number | undefined>,
) {
  const q = toQuery(params);
  return json<WhatIfBaseline>(`/api/whatif/baseline${q ? `?${q}` : ""}`);
}

export type WhatIfStrategy = {
  id: string;
  name: string;
  statuses: string[];
  param_label: string | null;
  default_param: string;
  param_kind: string;
  qty_effect: string;
  price_effect: string;
  summary: string;
  tiers?: { id: string; label: string; param: string; lift: number }[];
  default_tier?: string;
};

export type WhatIfStrategiesResponse = {
  ok: boolean;
  status: string | null;
  status_group: string | null;
  status_group_labels: Record<string, string>;
  traffic_tiers: { id: string; label: string; param: string; lift: number }[];
  default_traffic_tier: string;
  strategies: WhatIfStrategy[];
  total: number;
};

export async function fetchWhatIfStrategies(
  params?: Record<string, string | undefined>,
) {
  const q = toQuery(params || {});
  return json<WhatIfStrategiesResponse>(
    `/api/whatif/strategies${q ? `?${q}` : ""}`,
  );
}

export type WhatIfModelRow = {
  sku: string;
  channel_l3?: string | null;
  category?: string | null;
  status?: string | null;
  baseline_qty: number;
  baseline_price?: number | null;
  cost_price?: number | null;
  sim_amount?: number | null;
  sim_gross_profit?: number | null;
  elasticity_coef?: number | null;
  elasticity_class?: string | null;
  details?: WhatIfDetail[];
  strategy_id?: string | null;
  param?: string | null;
  traffic_tier?: string | null;
  target_qty?: number;
  target_revenue?: number | null;
};

export type WhatIfModelResultRow = WhatIfModelRow & {
  strategy_id: string;
  strategy_name?: string;
  sim_qty: number;
  sim_price: number | null;
  price_coverage_qty?: number;
  price_status?: string;
  cost_coverage_qty?: number;
  cost_status?: string;
  gross_coverage_qty?: number;
  gross_profit_status?: string;
  effect_note?: string;
  gap?: number;
};

export type WhatIfTask = {
  status: "pending" | "running" | "completed" | "failed" | string;
  progress?: string | null;
  result?: { rows?: WhatIfModelResultRow[] } | null;
  error_message?: string | null;
};

export async function submitWhatIfSimulation(rows: WhatIfModelRow[]) {
  return json<{ task_id: string; status: string }>("/api/whatif/simulate", {
    method: "POST",
    body: JSON.stringify({
      strategy_id: "maintain",
      param: null,
      traffic_tier: null,
      rows,
    }),
  });
}

export async function submitWhatIfOptimization(
  targetQty: number,
  targetRevenue: number | undefined,
  rows: WhatIfModelRow[],
) {
  return json<{ task_id: string; status: string }>("/api/whatif/optimize", {
    method: "POST",
    body: JSON.stringify({
      target_qty: targetQty,
      ...(targetRevenue != null ? { target_revenue: targetRevenue } : {}),
      param: null,
      traffic_tier: null,
      rows,
    }),
  });
}

export async function fetchWhatIfTask(taskId: string) {
  return json<WhatIfTask>(`/api/whatif/tasks/${encodeURIComponent(taskId)}`);
}
