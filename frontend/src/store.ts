import { create } from "zustand";
import type { AgentResultEnvelope, ChatMessage, ChatParams, Intent, SessionSummary } from "./types";
import * as api from "./api";
import { useAuthStore } from "./authStore";

/** 是否含右侧工作区可回看内容（图表或数据表） */
export function hasWorkbenchContent(env?: AgentResultEnvelope | null): boolean {
  if (!env) return false;
  return Boolean(env.table || env.chart);
}

interface AppState {
  sessionId: string | null;
  sessions: SessionSummary[];
  messages: ChatMessage[];
  envelope: AgentResultEnvelope | null;
  /** 当前工作区对应的助手消息 id（用于「查看」高亮） */
  viewingMessageId: string | null;
  params: ChatParams;
  loading: boolean;
  streamingReply: string;
  stage: string | null;
  processSteps: string[];
  mcpOk: boolean | null;
  mcpMode: string;
  error: string | null;
  setIntent: (intent: Intent | undefined) => void;
  refreshSessions: () => Promise<void>;
  checkAgent: () => Promise<void>;
  /** @deprecated use checkAgent */
  checkMcp: () => Promise<void>;
  loadSession: (id: string) => Promise<void>;
  newSession: () => void;
  renameSession: (id: string, title: string) => Promise<void>;
  togglePinSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  /** 将右侧工作区回滚到某条助手回复的结果 */
  viewMessageWorkspace: (messageId: string) => void;
  /** 发送用户消息；query 原样传给 Agent（不做筛选条件拼接） */
  send: (text: string, paramsOverride?: ChatParams) => Promise<void>;
}

const defaultParams: ChatParams = {};

export const useAppStore = create<AppState>((set, get) => ({
  sessionId: null,
  sessions: [],
  messages: [],
  envelope: null,
  viewingMessageId: null,
  params: defaultParams,
  loading: false,
  streamingReply: "",
  stage: null,
  processSteps: [],
  mcpOk: null,
  mcpMode: "mock",
  error: null,

  setIntent: (intent) => set((s) => ({ params: { ...s.params, intent } })),

  refreshSessions: async () => {
    try {
      const sessions = await api.fetchSessions();
      set({ sessions });
    } catch {
      /* ignore on first boot */
    }
  },

  checkAgent: async () => {
    try {
      const h = await api.fetchAgentHealth();
      set({ mcpOk: h.ok, mcpMode: h.mode || h.configured_mode || "mock" });
    } catch {
      set({ mcpOk: false });
    }
  },

  checkMcp: async () => {
    await get().checkAgent();
  },

  loadSession: async (id) => {
    const detail = await api.fetchSession(id);
    const messages: ChatMessage[] = detail.messages.map((m) => ({
      id: m.id,
      role: m.role as ChatMessage["role"],
      content: m.content,
      envelope: m.result_envelope || null,
      processSteps: m.result_envelope?.process_steps?.slice(-40) || undefined,
      createdAt: m.created_at,
    }));
    const lastWorkspace = [...messages].reverse().find(
      (m) => m.role === "assistant" && hasWorkbenchContent(m.envelope),
    );
    set({
      sessionId: id,
      messages,
      envelope: lastWorkspace?.envelope || null,
      viewingMessageId: lastWorkspace?.id || null,
      error: null,
    });
  },

  newSession: () =>
    set({
      sessionId: null,
      messages: [],
      envelope: null,
      viewingMessageId: null,
      error: null,
      streamingReply: "",
      stage: null,
      processSteps: [],
    }),

  renameSession: async (id, title) => {
    const updated = await api.updateSession(id, { title });
    set((s) => ({
      sessions: s.sessions.map((item) => (item.id === id ? { ...item, ...updated } : item)),
    }));
  },

  togglePinSession: async (id) => {
    const current = get().sessions.find((item) => item.id === id);
    const nextPinned = !(current?.pinned);
    await api.updateSession(id, { pinned: nextPinned });
    await get().refreshSessions();
  },

  deleteSession: async (id) => {
    await api.deleteSession(id);
    if (get().sessionId === id) {
      set((s) => ({
        sessions: s.sessions.filter((item) => item.id !== id),
        sessionId: null,
        messages: [],
        envelope: null,
        viewingMessageId: null,
        error: null,
        streamingReply: "",
        stage: null,
        processSteps: [],
      }));
      return;
    }
    set((s) => ({ sessions: s.sessions.filter((item) => item.id !== id) }));
  },

  viewMessageWorkspace: (messageId) => {
    const msg = get().messages.find((m) => m.id === messageId);
    if (!msg || msg.role !== "assistant" || !hasWorkbenchContent(msg.envelope)) return;
    set({
      envelope: msg.envelope || null,
      viewingMessageId: messageId,
      error: null,
    });
  },

  send: async (text, paramsOverride) => {
    if (get().loading) return;
    const query = (text || "").trim();
    if (!query) return;

    const params = { ...get().params, ...(paramsOverride || {}) };
    if (paramsOverride) {
      set({ params });
    }

    const auth = useAuthStore.getState();
    if (!auth.isAuthenticated()) {
      set({ error: "请先登录" });
      return;
    }

    const tempId = `tmp-${Date.now()}`;
    const nowIso = new Date().toISOString();
    set((s) => ({
      loading: true,
      streamingReply: "",
      stage: "思考",
      processSteps: ["正在思考…"],
      error: null,
      messages: [
        ...s.messages,
        { id: tempId, role: "user", content: query, createdAt: nowIso },
      ],
    }));
    try {
      const token = await auth.ensureValidToken();
      const res = await api.sendChatStream(
        query,
        get().sessionId,
        params,
        (status) => {
          const steps = status.steps?.length
            ? status.steps
            : status.text
              ? [...get().processSteps, status.text]
              : get().processSteps;
          set({
            stage: status.text || status.stage || "处理中…",
            processSteps: steps.slice(-40),
          });
        },
        (delta) => {
          set((s) => ({
            streamingReply: s.streamingReply + delta,
            stage: "正在生成回答…",
          }));
        },
        {
          oa: token.oa,
          backupAccessToken: token.backupAccessToken,
          oauthAccessToken: token.oauthAccessToken,
        },
      );
      const shouldUpdateWorkspace =
        res.update_workspace !== false && res.envelope?.update_workspace !== false;
      const steps =
        (res.steps && res.steps.length ? res.steps : get().processSteps).slice(-40);
      const envelopeSteps = (res.envelope?.process_steps?.length
        ? res.envelope.process_steps
        : steps
      ).slice(-40);
      const envelope = res.envelope
        ? {
            ...res.envelope,
            process_steps: envelopeSteps,
          }
        : res.envelope;
      const canView = hasWorkbenchContent(envelope);
      set((s) => ({
        sessionId: res.session_id,
        envelope: shouldUpdateWorkspace && envelope ? envelope : s.envelope,
        viewingMessageId:
          shouldUpdateWorkspace && canView ? res.message_id : s.viewingMessageId,
        messages: [
          ...s.messages,
          {
            id: res.message_id,
            role: "assistant",
            content: res.reply,
            envelope,
            processSteps: steps,
            createdAt: new Date().toISOString(),
          },
        ],
        loading: false,
        streamingReply: "",
        stage: null,
        processSteps: [],
      }));
      await get().refreshSessions();
    } catch (e) {
      set({
        loading: false,
        streamingReply: "",
        stage: null,
        processSteps: [],
        error: e instanceof Error ? e.message : "请求失败",
      });
    }
  },
}));
