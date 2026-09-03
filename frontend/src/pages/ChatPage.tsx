import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChatPanel } from "../components/ChatPanel";
import { useAppStore } from "../store";

export default function ChatPage() {
  const { sessionId: routeSessionId } = useParams();
  const navigate = useNavigate();
  const sessionId = useAppStore((s) => s.sessionId);
  const loadSession = useAppStore((s) => s.loadSession);
  const newSession = useAppStore((s) => s.newSession);

  useEffect(() => {
    if (!routeSessionId) {
      if (sessionId) {
        navigate(`/chat/${sessionId}`, { replace: true });
      } else {
        newSession();
      }
      return;
    }
    if (routeSessionId !== sessionId) {
      void loadSession(routeSessionId).catch(() => {
        newSession();
        navigate("/chat", { replace: true });
      });
    }
  }, [routeSessionId, sessionId, loadSession, newSession, navigate]);

  useEffect(() => {
    if (sessionId && !routeSessionId) {
      navigate(`/chat/${sessionId}`, { replace: true });
    }
  }, [sessionId, routeSessionId, navigate]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChatPanel embedded />
    </div>
  );
}
