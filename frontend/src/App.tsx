import { useEffect } from "react";
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

// ── Pages ────────────────────────────────────────────────────────────────────
import LoginPage from "@/pages/LoginPage";
import TOTPVerifyPage from "@/pages/TOTPVerifyPage";
import TOTPSetupPage from "@/pages/TOTPSetupPage";
import DashboardPage from "@/pages/DashboardPage";
import ProfilePage from "@/pages/ProfilePage";
import ConnectionsPage from "@/pages/ConnectionsPage";
import ConnectionFormPage from "@/pages/ConnectionFormPage";
import LLMProvidersPage from "@/pages/LLMProvidersPage";
import LLMProviderFormPage from "@/pages/LLMProviderFormPage";
import QueryPage from "@/pages/QueryPage";
import SavedQueriesPage from "@/pages/SavedQueriesPage";
import SchemaPage from "@/pages/SchemaPage";
import AdminPage from "@/pages/AdminPage";

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

              {/* Phase 4A — Connections (admin only enforced by backend) */}
              <Route path="connections" element={<ConnectionsPage />} />
              <Route path="connections/new" element={<ConnectionFormPage />} />
              <Route path="connections/:id/edit" element={<ConnectionFormPage />} />

              {/* Phase 4B — LLM Providers (admin only enforced by backend) */}
              <Route path="llm-providers" element={<LLMProvidersPage />} />
              <Route path="llm-providers/new" element={<LLMProviderFormPage />} />
              <Route path="llm-providers/:id/edit" element={<LLMProviderFormPage />} />

              {/* Phase 4C — AI Query (analyst+ enforced by backend) */}
              <Route path="query" element={<QueryPage />} />

              {/* Phase 4D — Saved Queries (ownership enforced by backend) */}
              <Route path="saved-queries" element={<SavedQueriesPage />} />

              {/* Phase 5 — Schema Browser (analyst+ enforced by backend) */}
              <Route path="schema-browser" element={<SchemaPage />} />

              {/* Phase 4E — Admin Panel (admin only enforced by backend) */}
              <Route path="admin" element={<AdminPage />} />
            </Route>
          </Route>

          {/* ── Catch-all ───────────────────────────────────────────────── */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthInitializer>
    </BrowserRouter>
  );
}