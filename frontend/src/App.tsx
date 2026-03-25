import { useEffect, lazy, Suspense } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";

import { useAuthStore } from "@/stores/auth-store";
import { ProtectedRoute } from "@/components/auth";
import { LoadingScreen } from "@/components/ui";
import AppShell from "@/components/AppShell";

// ── Light Pages (direct import — small bundles) ─────────────────────────────
import LoginPage from "@/pages/LoginPage";
import TOTPVerifyPage from "@/pages/TOTPVerifyPage";
import TOTPSetupPage from "@/pages/TOTPSetupPage";
import DashboardPage from "@/pages/DashboardPage";
import ProfilePage from "@/pages/ProfilePage";

// ── Heavy Pages (lazy loaded — Monaco, Recharts, TanStack Table) ────────────
const ConnectionsPage = lazy(() => import("@/pages/ConnectionsPage"));
const ConnectionFormPage = lazy(() => import("@/pages/ConnectionFormPage"));
const LLMProvidersPage = lazy(() => import("@/pages/LLMProvidersPage"));
const LLMProviderFormPage = lazy(() => import("@/pages/LLMProviderFormPage"));
const QueryPage = lazy(() => import("@/pages/QueryPage"));
const SavedQueriesPage = lazy(() => import("@/pages/SavedQueriesPage"));
const SchemaPage = lazy(() => import("@/pages/SchemaPage"));
const StudioPage = lazy(() => import("@/pages/StudioPage"));
const NotificationsPage = lazy(() => import("@/pages/NotificationsPage"));
const SchedulesPage = lazy(() => import("@/pages/SchedulesPage"));
const PermissionsPage = lazy(() => import("@/pages/PermissionsPage"));
const MonitoringPage = lazy(() => import("@/pages/MonitoringPage"));
const AdminPage = lazy(() => import("@/pages/AdminPage"));

// ─── Auth Initializer ────────────────────────────────────────────────────────

function AuthInitializer({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize);
  const phase = useAuthStore((s) => s.phase);

  useEffect(() => {
    initialize();
  }, [initialize]);

  if (phase === "idle") {
    return <LoadingScreen />;
  }

  return <>{children}</>;
}

// ─── App ─────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <AuthInitializer>
        <Routes>
          {/* ── Public Auth Routes ──────────────────────────────────────── */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/totp-verify" element={<TOTPVerifyPage />} />
          <Route path="/auth/totp-setup" element={<TOTPSetupPage />} />

          {/* ── Protected Routes (require authenticated phase) ──────────── */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route path="profile" element={<ProfilePage />} />

              {/* All lazy-loaded pages wrapped in Suspense */}
              <Route path="connections" element={<Suspense fallback={<LoadingScreen />}><ConnectionsPage /></Suspense>} />
              <Route path="connections/new" element={<Suspense fallback={<LoadingScreen />}><ConnectionFormPage /></Suspense>} />
              <Route path="connections/:id/edit" element={<Suspense fallback={<LoadingScreen />}><ConnectionFormPage /></Suspense>} />
              <Route path="llm-providers" element={<Suspense fallback={<LoadingScreen />}><LLMProvidersPage /></Suspense>} />
              <Route path="llm-providers/new" element={<Suspense fallback={<LoadingScreen />}><LLMProviderFormPage /></Suspense>} />
              <Route path="llm-providers/:id/edit" element={<Suspense fallback={<LoadingScreen />}><LLMProviderFormPage /></Suspense>} />
              <Route path="query" element={<Suspense fallback={<LoadingScreen />}><QueryPage /></Suspense>} />
              <Route path="saved-queries" element={<Suspense fallback={<LoadingScreen />}><SavedQueriesPage /></Suspense>} />
              <Route path="schema-browser" element={<Suspense fallback={<LoadingScreen />}><SchemaPage /></Suspense>} />
              <Route path="studio" element={<Suspense fallback={<LoadingScreen />}><StudioPage /></Suspense>} />
              <Route path="notifications" element={<Suspense fallback={<LoadingScreen />}><NotificationsPage /></Suspense>} />
              <Route path="schedules" element={<Suspense fallback={<LoadingScreen />}><SchedulesPage /></Suspense>} />
              <Route path="admin/permissions" element={<Suspense fallback={<LoadingScreen />}><PermissionsPage /></Suspense>} />
              <Route path="monitoring" element={<Suspense fallback={<LoadingScreen />}><MonitoringPage /></Suspense>} />
              <Route path="admin" element={<Suspense fallback={<LoadingScreen />}><AdminPage /></Suspense>} />
            </Route>
          </Route>

          {/* ── Catch-all ───────────────────────────────────────────────── */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthInitializer>
    </BrowserRouter>
  );
}