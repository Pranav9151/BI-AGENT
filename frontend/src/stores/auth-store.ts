/**
 * Smart BI Agent — Auth Store (Zustand)
 *
 * Manages the complete authentication lifecycle:
 *   - Login (email/password → full access or TOTP gate)
 *   - TOTP verification and setup flows
 *   - Token refresh via HttpOnly cookie
 *   - Auto-refresh before expiry (proactive, not reactive)
 *   - Session expiry detection and forced logout
 *   - User profile loading from /auth/me
 *
 * Token storage: in-memory only (never localStorage — T9 compliance).
 * Refresh token: HttpOnly cookie managed by backend (invisible to JS).
 */

import { create } from "zustand";
import { api, bindAuthFunctions, ApiRequestError } from "@/lib/api";
import type {
  LoginRequest,
  LoginResponse,
  User,
  TOTPVerifyResponse,
  TOTPSetupResponse,
  TOTPConfirmResponse,
  RefreshResponse,
  UserUpdateRequest,
} from "@/types/auth";

// ─── Types ───────────────────────────────────────────────────────────────────

type AuthPhase =
  | "idle"            // Initial state — checking if session exists
  | "unauthenticated" // No valid session
  | "totp_verify"     // Admin needs TOTP code entry
  | "totp_setup"      // Admin needs TOTP first-time setup
  | "authenticated";  // Full access granted

interface AuthState {
  // State
  phase: AuthPhase;
  user: User | null;
  accessToken: string | null;
  preTotpToken: string | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  login: (creds: LoginRequest) => Promise<void>;
  verifyTotp: (code: string) => Promise<void>;
  setupTotp: () => Promise<TOTPSetupResponse>;
  confirmTotp: (code: string) => Promise<void>;
  refreshToken: () => Promise<boolean>;
  fetchUser: () => Promise<void>;
  updateProfile: (data: UserUpdateRequest) => Promise<void>;
  logout: () => Promise<void>;
  forceLogout: () => void;
  initialize: () => Promise<void>;
  clearError: () => void;
}

// ─── Token Expiry Helpers ────────────────────────────────────────────────────

function parseJwtExp(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.exp ?? null;
  } catch {
    return null;
  }
}

let _refreshTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleRefresh(token: string, doRefresh: () => Promise<boolean>) {
  if (_refreshTimer) clearTimeout(_refreshTimer);

  const exp = parseJwtExp(token);
  if (!exp) return;

  // Refresh 60 seconds before expiry (access tokens are 15min)
  const msUntilRefresh = (exp * 1000) - Date.now() - 60_000;
  if (msUntilRefresh <= 0) {
    // Already close to expiry — refresh immediately
    doRefresh();
    return;
  }

  _refreshTimer = setTimeout(() => {
    doRefresh();
  }, msUntilRefresh);
}

function clearRefreshTimer() {
  if (_refreshTimer) {
    clearTimeout(_refreshTimer);
    _refreshTimer = null;
  }
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useAuthStore = create<AuthState>((set, get) => {
  // Wire up the API client's auth functions immediately
  bindAuthFunctions({
    getToken: () => get().accessToken,
    getPreTotpToken: () => get().preTotpToken,
    refresh: () => get().refreshToken(),
    logout: () => get().forceLogout(),
  });

  return {
    // ── Initial State ──────────────────────────────────────────────────────
    phase: "idle",
    user: null,
    accessToken: null,
    preTotpToken: null,
    isLoading: false,
    error: null,

    clearError: () => set({ error: null }),

    // ── Login ──────────────────────────────────────────────────────────────
    login: async (creds: LoginRequest) => {
      set({ isLoading: true, error: null });
      try {
        const data = await api.post<LoginResponse>("/auth/login", creds, {
          skipRetry: true,
        });

        if (data.totp_required && data.totp_setup_required) {
          // Admin: first-time TOTP setup needed
          set({
            phase: "totp_setup",
            preTotpToken: data.access_token,
            accessToken: null,
            isLoading: false,
          });
        } else if (data.totp_required) {
          // Admin: TOTP verification needed
          set({
            phase: "totp_verify",
            preTotpToken: data.access_token,
            accessToken: null,
            isLoading: false,
          });
        } else {
          // Full access granted (non-admin or admin with TOTP already done)
          set({
            phase: "authenticated",
            accessToken: data.access_token,
            preTotpToken: null,
            isLoading: false,
          });
          scheduleRefresh(data.access_token, get().refreshToken);
          await get().fetchUser();
        }
      } catch (err) {
        const message =
          err instanceof ApiRequestError
            ? err.message
            : "An unexpected error occurred.";
        set({ isLoading: false, error: message });
        throw err;
      }
    },

    // ── TOTP Verify ────────────────────────────────────────────────────────
    verifyTotp: async (code: string) => {
      set({ isLoading: true, error: null });
      try {
        const data = await api.post<TOTPVerifyResponse>(
          "/auth/totp/verify",
          { code },
          { usePreTotp: true, skipRetry: true }
        );
        set({
          phase: "authenticated",
          accessToken: data.access_token,
          preTotpToken: null,
          isLoading: false,
        });
        scheduleRefresh(data.access_token, get().refreshToken);
        await get().fetchUser();
      } catch (err) {
        const message =
          err instanceof ApiRequestError
            ? err.message
            : "Verification failed.";
        set({ isLoading: false, error: message });
        throw err;
      }
    },

    // ── TOTP Setup ─────────────────────────────────────────────────────────
    setupTotp: async () => {
      set({ isLoading: true, error: null });
      try {
        const data = await api.post<TOTPSetupResponse>(
          "/auth/totp/setup",
          undefined,
          { usePreTotp: true, skipRetry: true }
        );
        set({ isLoading: false });
        return data;
      } catch (err) {
        const message =
          err instanceof ApiRequestError
            ? err.message
            : "TOTP setup failed.";
        set({ isLoading: false, error: message });
        throw err;
      }
    },

    // ── TOTP Confirm ───────────────────────────────────────────────────────
    confirmTotp: async (code: string) => {
      set({ isLoading: true, error: null });
      try {
        await api.post<TOTPConfirmResponse>(
          "/auth/totp/confirm",
          { code },
          { usePreTotp: true, skipRetry: true }
        );
        // After confirmation, user needs to log in fresh with TOTP
        set({
          phase: "unauthenticated",
          preTotpToken: null,
          accessToken: null,
          isLoading: false,
          error: null,
        });
      } catch (err) {
        const message =
          err instanceof ApiRequestError
            ? err.message
            : "TOTP confirmation failed.";
        set({ isLoading: false, error: message });
        throw err;
      }
    },

    // ── Token Refresh ──────────────────────────────────────────────────────
    refreshToken: async () => {
      try {
        const data = await api.post<RefreshResponse>(
          "/auth/refresh",
          undefined,
          { skipRetry: true }
        );
        set({ accessToken: data.access_token });
        scheduleRefresh(data.access_token, get().refreshToken);
        return true;
      } catch {
        // Refresh failed — session expired
        clearRefreshTimer();
        set({
          phase: "unauthenticated",
          accessToken: null,
          preTotpToken: null,
          user: null,
        });
        return false;
      }
    },

    // ── Fetch User Profile ─────────────────────────────────────────────────
    fetchUser: async () => {
      try {
        const user = await api.get<User>("/auth/me");
        set({ user });
      } catch {
        // If /me fails after authentication, something is very wrong
        get().forceLogout();
      }
    },

    // ── Update Profile ─────────────────────────────────────────────────────
    updateProfile: async (data: UserUpdateRequest) => {
      const user = get().user;
      if (!user) return;
      set({ isLoading: true, error: null });
      try {
        const updated = await api.patch<User>(
          `/users/${user.user_id}`,
          data
        );
        set({ user: updated, isLoading: false });
      } catch (err) {
        const message =
          err instanceof ApiRequestError
            ? err.message
            : "Profile update failed.";
        set({ isLoading: false, error: message });
        throw err;
      }
    },

    // ── Logout ─────────────────────────────────────────────────────────────
    logout: async () => {
      clearRefreshTimer();
      try {
        await api.post("/auth/logout", undefined, { skipRetry: true });
      } catch {
        // Logout always succeeds from client perspective
      }
      set({
        phase: "unauthenticated",
        accessToken: null,
        preTotpToken: null,
        user: null,
        error: null,
      });
    },

    // ── Force Logout (no API call — used when token is already invalid) ───
    forceLogout: () => {
      clearRefreshTimer();
      set({
        phase: "unauthenticated",
        accessToken: null,
        preTotpToken: null,
        user: null,
        error: null,
      });
    },

    // ── Initialize (called on app mount — try to restore session) ─────────
    initialize: async () => {
      set({ phase: "idle", isLoading: true });
      try {
        // Try refreshing with HttpOnly cookie — if it works, we have a session
        const data = await api.post<RefreshResponse>(
          "/auth/refresh",
          undefined,
          { skipRetry: true }
        );
        set({ accessToken: data.access_token });
        scheduleRefresh(data.access_token, get().refreshToken);

        // Load user profile
        const user = await api.get<User>("/auth/me");
        set({
          phase: "authenticated",
          user,
          isLoading: false,
        });
      } catch {
        // No valid session — that's fine, user needs to log in
        set({
          phase: "unauthenticated",
          isLoading: false,
        });
      }
    },
  };
});
