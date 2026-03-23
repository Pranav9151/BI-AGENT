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
            </Route>
          </Route>

          {/* ── Catch-all ───────────────────────────────────────────────── */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthInitializer>
    </BrowserRouter>
  );
}
