import { create } from "zustand";
import * as api from "./api";

const STORAGE_KEY = "forecast-agent-auth";
export const TOKEN_EXPIRY_SKEW_MS = 60_000;

export type AuthSession = {
  mode: "oa" | "email";
  oa: string | null;
  email: string | null;
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresAt: number;
  oauthAccessToken: string | null;
  oauthTokenType: string | null;
  oauthExpiresAt: number;
};

export type AuthToken = {
  mode: "oa" | "email";
  oa: string | null;
  email: string | null;
  backupAccessToken: string;
  oauthAccessToken: string | null;
};

type AuthState = AuthSession & {
  hydrated: boolean;
  hydrate: () => void;
  isAuthenticated: () => boolean;
  isTokenValid: () => boolean;
  ensureValidToken: () => Promise<AuthToken>;
  login: (oa: string) => Promise<void>;
  loginEmail: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const EMPTY_SESSION: AuthSession = {
  mode: "oa",
  oa: null,
  email: null,
  accessToken: "",
  refreshToken: "",
  tokenType: "bearer",
  expiresAt: 0,
  oauthAccessToken: null,
  oauthTokenType: null,
  oauthExpiresAt: 0,
};

function positiveNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function sessionFromUnknown(value: unknown): AuthSession | null {
  if (!value || typeof value !== "object") return null;
  const parsed = value as Partial<AuthSession>;
  if (parsed.mode !== "oa" && parsed.mode !== "email") return null;
  if (typeof parsed.accessToken !== "string" || !parsed.accessToken) return null;
  if (typeof parsed.refreshToken !== "string" || !parsed.refreshToken) return null;
  if (typeof parsed.tokenType !== "string" || !parsed.tokenType) return null;
  if (typeof parsed.expiresAt !== "number" || !Number.isFinite(parsed.expiresAt)) return null;
  if (typeof parsed.oauthExpiresAt !== "number" || !Number.isFinite(parsed.oauthExpiresAt)) return null;
  if (parsed.mode === "oa") {
    if (typeof parsed.oa !== "string" || !parsed.oa) return null;
    if (typeof parsed.oauthAccessToken !== "string" || !parsed.oauthAccessToken) return null;
    if (typeof parsed.oauthTokenType !== "string" || !parsed.oauthTokenType) return null;
  } else if (typeof parsed.email !== "string" || !parsed.email) {
    return null;
  }
  return {
    mode: parsed.mode,
    oa: parsed.mode === "oa" ? parsed.oa! : null,
    email: parsed.mode === "email" ? parsed.email || null : null,
    accessToken: parsed.accessToken,
    refreshToken: parsed.refreshToken,
    tokenType: parsed.tokenType,
    expiresAt: parsed.expiresAt,
    oauthAccessToken: parsed.mode === "oa" ? parsed.oauthAccessToken! : null,
    oauthTokenType: parsed.mode === "oa" ? parsed.oauthTokenType! : null,
    oauthExpiresAt: parsed.mode === "oa" ? parsed.oauthExpiresAt : 0,
  };
}

function loadStored(): AuthSession | null {
  try {
    return sessionFromUnknown(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
  } catch {
    return null;
  }
}

function saveStored(session: AuthSession | null) {
  try {
    if (!session) {
      localStorage.removeItem(STORAGE_KEY);
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      mode: session.mode,
      oa: session.oa,
      email: session.email,
      accessToken: session.accessToken,
      refreshToken: session.refreshToken,
      tokenType: session.tokenType,
      expiresAt: session.expiresAt,
      oauthAccessToken: session.oauthAccessToken,
      oauthTokenType: session.oauthTokenType,
      oauthExpiresAt: session.oauthExpiresAt,
    }));
  } catch {
    /* localStorage may be unavailable; the in-memory session remains usable */
  }
}

function applySession(
  set: (partial: Partial<AuthState>) => void,
  session: AuthSession,
) {
  saveStored(session);
  set({ ...session, hydrated: true });
}

function validateOaResponse(res: api.OaLoginResponse) {
  if (
    !res?.access_token ||
    !res.refresh_token ||
    !positiveNumber(res.expires_in) ||
    !res.oauth_access_token ||
    !positiveNumber(res.oauth_expires_in)
  ) {
    throw new Error("登录响应无效");
  }
  return res;
}

function validateOAuthRenewalResponse(res: api.OaLoginResponse) {
  if (!res?.oauth_access_token || !positiveNumber(res.oauth_expires_in)) {
    throw new Error("登录响应无效");
  }
  return res;
}

function validateBackupResponse(res: api.BackupTokenResponse) {
  if (!res?.access_token || !res.refresh_token || !positiveNumber(res.expires_in)) {
    throw new Error("登录响应无效");
  }
  return res;
}

let authEventRegistered = false;

export const useAuthStore = create<AuthState>((set, get) => {
  const registerAuthEvent = () => {
    if (authEventRegistered || typeof window === "undefined") return;
    authEventRegistered = true;
    window.addEventListener("forecast-agent-auth-updated", () => {
      const stored = loadStored();
      set(stored ? { ...stored, hydrated: true } : { ...EMPTY_SESSION, hydrated: true });
    });
  };

  return {
    ...EMPTY_SESSION,
    hydrated: false,

    hydrate: () => {
      registerAuthEvent();
      const stored = loadStored();
      set(stored ? { ...stored, hydrated: true } : { ...EMPTY_SESSION, hydrated: true });
    },

    isAuthenticated: () => {
      const { accessToken, refreshToken, expiresAt } = get();
      return Boolean((accessToken && expiresAt > Date.now()) || refreshToken);
    },

    isTokenValid: () => {
      const { accessToken, expiresAt } = get();
      return Boolean(accessToken) && expiresAt > Date.now() + TOKEN_EXPIRY_SKEW_MS;
    },

    ensureValidToken: async () => {
      let session: AuthSession = {
        mode: get().mode,
        oa: get().oa,
        email: get().email,
        accessToken: get().accessToken,
        refreshToken: get().refreshToken,
        tokenType: get().tokenType,
        expiresAt: get().expiresAt,
        oauthAccessToken: get().oauthAccessToken,
        oauthTokenType: get().oauthTokenType,
        oauthExpiresAt: get().oauthExpiresAt,
      };

      try {
        if (!session.accessToken && !session.refreshToken) {
          throw new Error("登录已过期，请重新登录");
        }

        if (session.expiresAt <= Date.now() + TOKEN_EXPIRY_SKEW_MS) {
          if (!session.refreshToken) throw new Error("登录已过期，请重新登录");
          const refreshed = validateBackupResponse(await api.refreshWithToken(session.refreshToken));
          session = {
            ...session,
            accessToken: refreshed.access_token,
            refreshToken: refreshed.refresh_token,
            tokenType: refreshed.token_type || session.tokenType || "bearer",
            expiresAt: Date.now() + refreshed.expires_in * 1000,
          };
          applySession(set, session);
        }

        if (session.mode === "oa") {
          if (!session.oa) throw new Error("登录已过期，请重新登录");
          if (
            !session.oauthAccessToken ||
            session.oauthExpiresAt <= Date.now() + TOKEN_EXPIRY_SKEW_MS
          ) {
            const renewed = validateOAuthRenewalResponse(await api.loginWithOa(session.oa));
            const hasNewBackupTokens = Boolean(
              renewed.access_token &&
              renewed.refresh_token &&
              positiveNumber(renewed.expires_in),
            );
            session = {
              ...session,
              oa: renewed.oa || session.oa,
              accessToken: hasNewBackupTokens ? renewed.access_token : session.accessToken,
              refreshToken: hasNewBackupTokens ? renewed.refresh_token : session.refreshToken,
              tokenType: hasNewBackupTokens
                ? renewed.token_type || session.tokenType || "bearer"
                : session.tokenType,
              expiresAt: hasNewBackupTokens && positiveNumber(renewed.expires_in)
                ? Date.now() + renewed.expires_in * 1000
                : session.expiresAt,
              oauthAccessToken: renewed.oauth_access_token,
              oauthTokenType: renewed.oauth_token_type || "bearer",
              oauthExpiresAt: Date.now() + renewed.oauth_expires_in * 1000,
            };
            applySession(set, session);
          }
        } else {
          session = { ...session, oa: null, oauthAccessToken: null, oauthTokenType: null, oauthExpiresAt: 0 };
          applySession(set, session);
        }

        return {
          mode: session.mode,
          oa: session.oa,
          email: session.email,
          backupAccessToken: session.accessToken,
          oauthAccessToken: session.oauthAccessToken,
        };
      } catch (error) {
        saveStored(null);
        set({ ...EMPTY_SESSION, hydrated: true });
        if (error instanceof Error && error.message === "登录已过期，请重新登录") {
          throw error;
        }
        throw new Error("登录已过期，请重新登录");
      }
    },

    login: async (oa) => {
      try {
        const normalizedOa = oa.trim();
        const res = validateOaResponse(await api.loginWithOa(normalizedOa));
        applySession(set, {
          mode: "oa",
          oa: res.oa || normalizedOa,
          email: null,
          accessToken: res.access_token,
          refreshToken: res.refresh_token,
          tokenType: res.token_type || "bearer",
          expiresAt: Date.now() + res.expires_in * 1000,
          oauthAccessToken: res.oauth_access_token,
          oauthTokenType: res.oauth_token_type || "bearer",
          oauthExpiresAt: Date.now() + res.oauth_expires_in * 1000,
        });
      } catch (error) {
        saveStored(null);
        set({ ...EMPTY_SESSION, hydrated: true });
        throw error;
      }
    },

    loginEmail: async (email, password) => {
      try {
        const normalizedEmail = email.trim().toLowerCase();
        const res = validateBackupResponse(await api.loginWithEmail(normalizedEmail, password));
        applySession(set, {
          mode: "email",
          oa: null,
          email: normalizedEmail,
          accessToken: res.access_token,
          refreshToken: res.refresh_token,
          tokenType: res.token_type || "bearer",
          expiresAt: Date.now() + res.expires_in * 1000,
          oauthAccessToken: null,
          oauthTokenType: null,
          oauthExpiresAt: 0,
        });
      } catch (error) {
        saveStored(null);
        set({ ...EMPTY_SESSION, hydrated: true });
        throw error;
      }
    },

    logout: () => {
      const { accessToken, refreshToken } = get();
      if (accessToken && refreshToken) void api.logoutWithToken(accessToken, refreshToken);
      saveStored(null);
      set({ ...EMPTY_SESSION, hydrated: true });
    },
  };
});
