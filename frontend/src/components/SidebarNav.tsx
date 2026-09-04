import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  CaretDown,
  ChatCircleText,
  Database,
  GearSix,
  PencilSimple,
  Plus,
  PushPin,
  Table,
  Trash,
  TreeStructure,
  Flask,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { useAppStore } from "../store";

type Props = {
  onNavigate?: () => void;
};

export function SidebarNav({ onNavigate }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const sessions = useAppStore((s) => s.sessions);
  const sessionId = useAppStore((s) => s.sessionId);
  const loadSession = useAppStore((s) => s.loadSession);
  const newSession = useAppStore((s) => s.newSession);
  const refreshSessions = useAppStore((s) => s.refreshSessions);
  const renameSession = useAppStore((s) => s.renameSession);
  const togglePinSession = useAppStore((s) => s.togglePinSession);
  const deleteSession = useAppStore((s) => s.deleteSession);

  const [wbOpen, setWbOpen] = useState(true);
  const [aiOpen, setAiOpen] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    if (location.pathname.startsWith("/chat")) setAiOpen(true);
    if (location.pathname.startsWith("/workbench")) setWbOpen(true);
  }, [location.pathname]);

  const orderedSessions = useMemo(() => {
    const pinned = sessions.filter((s) => s.pinned);
    const rest = sessions.filter((s) => !s.pinned);
    return [...pinned, ...rest];
  }, [sessions]);

  const go = (path: string) => {
    navigate(path);
    onNavigate?.();
  };

  const onNewChat = () => {
    setEditingId(null);
    setSessionError(null);
    newSession();
    go("/chat");
  };

  const onPickSession = async (id: string) => {
    setSessionError(null);
    try {
      await loadSession(id);
      go(`/chat/${id}`);
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "加载会话失败");
    }
  };

  const onStartRename = (event: ReactMouseEvent, id: string, title: string) => {
    event.stopPropagation();
    setSessionError(null);
    setEditingId(id);
    setEditTitle(title || "");
  };

  const onCommitRename = async () => {
    if (!editingId) return;
    const id = editingId;
    const nextTitle = editTitle.trim() || "未命名对话";
    const current = sessions.find((session) => session.id === id);
    setEditingId(null);
    if (current && nextTitle === (current.title || "未命名对话")) return;
    try {
      await renameSession(id, nextTitle);
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "重命名失败");
    }
  };

  const onTogglePin = async (event: ReactMouseEvent, id: string) => {
    event.stopPropagation();
    setSessionError(null);
    try {
      await togglePinSession(id);
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "置顶失败");
    }
  };

  const onDeleteSession = async (event: ReactMouseEvent, id: string, title: string) => {
    event.stopPropagation();
    if (!window.confirm(`确认删除会话“${title || "未命名对话"}”？`)) return;
    setSessionError(null);
    try {
      await deleteSession(id);
      if (id === sessionId) go("/chat");
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "删除失败");
    }
  };

  const itemClass = (active: boolean) =>
    `flex w-full items-center gap-2 rounded-lg border-l-2 px-3 py-2 text-left text-[13px] transition ${
      active
        ? "border-primary bg-primary/5 font-medium text-primary"
        : "border-transparent text-muted-fg hover:bg-muted hover:text-foreground"
    }`;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <div className="mb-1">
          <button
            type="button"
            onClick={() => setWbOpen((v) => !v)}
            className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-semibold text-foreground hover:bg-muted"
          >
            <Database size={16} className="text-primary" aria-hidden />
            预测工作台
            <CaretDown
              size={14}
              className={`ml-auto text-muted-fg transition ${wbOpen ? "" : "-rotate-90"}`}
              aria-hidden
            />
          </button>
          {wbOpen && (
            <div className="mt-0.5 space-y-0.5 pl-1">
              <NavLink
                to="/workbench/input"
                onClick={onNavigate}
                className={({ isActive }) => itemClass(isActive)}
              >
                输入数据
              </NavLink>
              <NavLink
                to="/workbench/params"
                onClick={onNavigate}
                className={({ isActive }) => itemClass(isActive)}
              >
                参数设置
              </NavLink>
              <NavLink
                to="/workbench/results"
                onClick={onNavigate}
                className={({ isActive }) => itemClass(isActive)}
              >
                <Table size={14} aria-hidden />
                预测结果
              </NavLink>
              <NavLink
                to="/workbench/attribution"
                onClick={onNavigate}
                className={({ isActive }) => itemClass(isActive)}
              >
                <TreeStructure size={14} aria-hidden />
                归因分析
              </NavLink>
              <NavLink
                to="/workbench/what-if"
                end
                onClick={onNavigate}
                className={({ isActive }) => itemClass(isActive)}
              >
                <Flask size={14} aria-hidden />
                What-if模拟
              </NavLink>
              <div className="ml-4 space-y-0.5 border-l border-border pl-2">
                <NavLink
                  to="/workbench/what-if/elasticity"
                  onClick={onNavigate}
                  className={({ isActive }) => itemClass(isActive)}
                >
                  价格弹性表
                </NavLink>
                <NavLink
                  to="/workbench/what-if/knowledge"
                  onClick={onNavigate}
                  className={({ isActive }) => itemClass(isActive)}
                >
                  策略知识库
                </NavLink>
              </div>
            </div>
          )}
        </div>

        <div className="mt-2">
          <button
            type="button"
            onClick={() => setAiOpen((v) => !v)}
            className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-semibold text-foreground hover:bg-muted"
          >
            <ChatCircleText size={16} className="text-primary" aria-hidden />
            AI 助手
            <CaretDown
              size={14}
              className={`ml-auto text-muted-fg transition ${aiOpen ? "" : "-rotate-90"}`}
              aria-hidden
            />
          </button>
          {aiOpen && (
            <div className="mt-0.5 space-y-0.5 pl-1">
              <button type="button" onClick={onNewChat} className={itemClass(location.pathname === "/chat" && !sessionId)}>
                <Plus size={14} weight="bold" aria-hidden />
                新对话
              </button>
              {sessionError && (
                <p className="rounded-md border border-rose-100 bg-rose-50 px-3 py-1.5 text-[11px] text-destructive">
                  {sessionError}
                </p>
              )}
              <div className="max-h-[46vh] space-y-0.5 overflow-y-auto py-1">
                {orderedSessions.length === 0 ? (
                  <p className="px-3 py-2 text-[11px] text-muted-fg">暂无历史对话</p>
                ) : (
                  orderedSessions.map((s) => {
                    const active =
                      sessionId === s.id && location.pathname.startsWith("/chat");
                    const editing = editingId === s.id;
                    return (
                      <div
                        key={s.id}
                        className={`group/session flex items-center gap-1 rounded-lg border-l-2 px-1 transition ${
                          active
                            ? "border-primary bg-primary/5 text-primary"
                            : "border-transparent hover:bg-muted"
                        }`}
                      >
                        {editing ? (
                          <input
                            autoFocus
                            value={editTitle}
                            maxLength={255}
                            onChange={(event) => setEditTitle(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onKeyDown={(event) => {
                              event.stopPropagation();
                              if (event.key === "Enter") {
                                event.preventDefault();
                                void onCommitRename();
                              } else if (event.key === "Escape") {
                                event.preventDefault();
                                setEditingId(null);
                              }
                            }}
                            onBlur={() => void onCommitRename()}
                            className="min-w-0 flex-1 rounded border border-primary/40 bg-white px-2 py-1 text-[13px] text-foreground outline-none focus:ring-2 focus:ring-primary/15"
                            aria-label="重命名对话"
                          />
                        ) : (
                          <button
                            type="button"
                            onClick={() => void onPickSession(s.id)}
                            className={`${itemClass(active)} min-w-0 flex-1 border-0 bg-transparent px-2 py-2`}
                            title={s.title}
                          >
                            <span className="min-w-0 flex-1 truncate">{s.title || "未命名对话"}</span>
                            {s.pinned ? (
                              <PushPin size={12} weight="fill" className="shrink-0 text-primary" aria-hidden />
                            ) : null}
                          </button>
                        )}
                        {!editing && (
                          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover/session:opacity-100 focus-within:opacity-100">
                            <button
                              type="button"
                              onClick={(event) => void onTogglePin(event, s.id)}
                              className={`inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-white hover:text-primary ${
                                s.pinned ? "opacity-100 text-primary" : ""
                              }`}
                              aria-label={s.pinned ? "取消置顶" : "置顶"}
                              title={s.pinned ? "取消置顶" : "置顶"}
                            >
                              <PushPin size={13} weight={s.pinned ? "fill" : "regular"} />
                            </button>
                            <button
                              type="button"
                              onClick={(event) => onStartRename(event, s.id, s.title)}
                              className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-white hover:text-foreground"
                              aria-label="重命名"
                              title="重命名"
                            >
                              <PencilSimple size={13} />
                            </button>
                            <button
                              type="button"
                              onClick={(event) => void onDeleteSession(event, s.id, s.title)}
                              className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded text-muted-fg transition hover:bg-rose-100 hover:text-destructive"
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

      <div className="border-t border-border px-3 py-2 text-[11px] text-muted-fg">
        <span className="inline-flex items-center gap-1">
          <GearSix size={12} aria-hidden />
          工作台导航
        </span>
      </div>
    </div>
  );
}
