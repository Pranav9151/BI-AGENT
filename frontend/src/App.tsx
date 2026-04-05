import React, { useEffect, lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";

import { useAuthStore } from "@/stores/auth-store";
import { ProtectedRoute } from "@/components/auth";
import { LoadingScreen } from "@/components/ui";
import AppShell from "@/components/AppShell";

// ── Configure Monaco to use LOCAL bundle (no CDN fetches, no eval CSP issues) ─
loader.config({ monaco });

// ── Light Pages ───────────────────────────────────────────────────────────────
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";
import TOTPVerifyPage from "@/pages/TOTPVerifyPage";
import TOTPSetupPage from "@/pages/TOTPSetupPage";
import DashboardPage from "@/pages/DashboardPage";
import ProfilePage from "@/pages/ProfilePage";

// ── Heavy Pages (lazy) ────────────────────────────────────────────────────────
const ConnectionsPage     = lazy(() => import("@/pages/ConnectionsPage"));
const ConnectionFormPage  = lazy(() => import("@/pages/ConnectionFormPage"));
const LLMProvidersPage    = lazy(() => import("@/pages/LLMProvidersPage"));
const LLMProviderFormPage = lazy(() => import("@/pages/LLMProviderFormPage"));
const QueryPage           = lazy(() => import("@/pages/QueryPage"));
const SavedQueriesPage    = lazy(() => import("@/pages/SavedQueriesPage"));
const SchemaPage          = lazy(() => import("@/pages/SchemaPage"));
const StudioPage = lazy(() => import("@/pages/StudioPage")); 
const NotificationsPage   = lazy(() => import("@/pages/NotificationsPage"));
const SchedulesPage       = lazy(() => import("@/pages/SchedulesPage"));
const PermissionsPage     = lazy(() => import("@/pages/PermissionsPage"));
const MonitoringPage      = lazy(() => import("@/pages/MonitoringPage"));
const AdminPage           = lazy(() => import("@/pages/AdminPage"));
const AlertsPage          = lazy(() => import("@/pages/AlertsPage"));

// ─── Error Boundary ───────────────────────────────────────────────────────────
// Without this, ANY render crash produces a completely blank page with zero
// visible feedback. This catches the crash, shows the exact error, and lets
// you retry — making every future bug trivially diagnosable.

interface EBState { error: Error | null; info: string }

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, EBState> {
  state: EBState = { error: null, info: "" };

  static getDerivedStateFromError(error: Error): EBState {
    return { error, info: "" };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary] caught:", error, info);
    this.setState({ error, info: info.componentStack ?? "" });
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div style={{
        padding: 40, background: "#0f172a", minHeight: "100vh",
        fontFamily: "ui-monospace, monospace", color: "#e2e8f0",
        display: "flex", flexDirection: "column", gap: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 28 }}>⚠️</span>
          <h1 style={{ margin: 0, color: "#fb923c", fontSize: 20 }}>
            Smart BI Agent — Render Error
          </h1>
        </div>

        <div style={{
          background: "#1e293b", border: "1px solid #ef4444",
          borderRadius: 8, padding: 20,
        }}>
          <p style={{ margin: "0 0 8px", color: "#f87171", fontWeight: "bold", fontSize: 14 }}>
            {error.name}: {error.message}
          </p>
          {error.stack && (
            <pre style={{
              margin: 0, fontSize: 12, color: "#94a3b8",
              whiteSpace: "pre-wrap", wordBreak: "break-all",
              maxHeight: 300, overflow: "auto",
            }}>
              {error.stack}
            </pre>
          )}
        </div>

        {info && (
          <div style={{
            background: "#1e293b", border: "1px solid #334155",
            borderRadius: 8, padding: 20,
          }}>
            <p style={{ margin: "0 0 8px", color: "#94a3b8", fontSize: 12, fontWeight: "bold" }}>
              Component Stack:
            </p>
            <pre style={{
              margin: 0, fontSize: 11, color: "#64748b",
              whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto",
            }}>
              {info}
            </pre>
          </div>
        )}

        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
          <button
            onClick={() => this.setState({ error: null, info: "" })}
            style={{
              padding: "8px 20px", background: "#3b82f6", color: "#fff",
              border: "none", borderRadius: 6, cursor: "pointer", fontSize: 14,
            }}
          >
            Try Again
          </button>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "8px 20px", background: "#1e293b", color: "#94a3b8",
              border: "1px solid #334155", borderRadius: 6, cursor: "pointer", fontSize: 14,
            }}
          >
            Reload Page
          </button>
        </div>

        <p style={{ margin: 0, color: "#475569", fontSize: 12 }}>
          Open DevTools (F12) → Console for the full stack trace.
        </p>
      </div>
    );
  }
}

// ─── Auth Initializer ─────────────────────────────────────────────────────────

function AuthInitializer({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize);
  const phase = useAuthStore((s) => s.phase);
  useEffect(() => { initialize(); }, [initialize]);
  if (phase === "idle") return <LoadingScreen />;
  return <>{children}</>;
}

/**
 * ScrollLayout — wraps normal pages in a scrollable padded container.
 * Studio and Query bypass this and render full-bleed inside AppShell.
 */
function ScrollLayout() {
  return (
    <div className="absolute inset-0 overflow-y-auto overflow-x-hidden p-4 lg:p-6">
      <Outlet />
    </div>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthInitializer>
          <Routes>
            {/* Public */}
            <Route path="/login"            element={<LoginPage />} />
            <Route path="/register"         element={<RegisterPage />} />
            <Route path="/auth/totp-verify" element={<TOTPVerifyPage />} />
            <Route path="/auth/totp-setup"  element={<TOTPSetupPage />} />

            {/* Protected */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>

                {/* ★ Full-bleed pages — fill the relative container directly */}
                <Route path="studio" element={<Suspense fallback={<LoadingScreen />}><StudioPage /></Suspense>} />
                <Route path="query"  element={<Suspense fallback={<LoadingScreen />}><QueryPage /></Suspense>} />

                {/* ★ Scrollable padded pages */}
                <Route element={<ScrollLayout />}>
                  <Route index          element={<DashboardPage />} />
                  <Route path="profile" element={<ProfilePage />} />
                  <Route path="connections"          element={<Suspense fallback={<LoadingScreen />}><ConnectionsPage /></Suspense>} />
                  <Route path="connections/new"      element={<Suspense fallback={<LoadingScreen />}><ConnectionFormPage /></Suspense>} />
                  <Route path="connections/:id/edit" element={<Suspense fallback={<LoadingScreen />}><ConnectionFormPage /></Suspense>} />
                  <Route path="llm-providers"            element={<Suspense fallback={<LoadingScreen />}><LLMProvidersPage /></Suspense>} />
                  <Route path="llm-providers/new"        element={<Suspense fallback={<LoadingScreen />}><LLMProviderFormPage /></Suspense>} />
                  <Route path="llm-providers/:id/edit"   element={<Suspense fallback={<LoadingScreen />}><LLMProviderFormPage /></Suspense>} />
                  <Route path="saved-queries"  element={<Suspense fallback={<LoadingScreen />}><SavedQueriesPage /></Suspense>} />
                  <Route path="schema-browser" element={<Suspense fallback={<LoadingScreen />}><SchemaPage /></Suspense>} />
                  <Route path="notifications"  element={<Suspense fallback={<LoadingScreen />}><NotificationsPage /></Suspense>} />
                  <Route path="schedules"      element={<Suspense fallback={<LoadingScreen />}><SchedulesPage /></Suspense>} />
                  <Route path="admin/permissions" element={<Suspense fallback={<LoadingScreen />}><PermissionsPage /></Suspense>} />
                  <Route path="monitoring" element={<Suspense fallback={<LoadingScreen />}><MonitoringPage /></Suspense>} />
                  <Route path="alerts"     element={<Suspense fallback={<LoadingScreen />}><AlertsPage /></Suspense>} />
                  <Route path="admin"      element={<Suspense fallback={<LoadingScreen />}><AdminPage /></Suspense>} />
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthInitializer>
      </BrowserRouter>
    </ErrorBoundary>
  );
}