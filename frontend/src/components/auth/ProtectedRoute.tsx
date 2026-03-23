import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/auth-store";
import { LoadingScreen } from "@/components/ui";

/**
 * Route guard that ensures user is authenticated.
 * Redirects to /login if not, preserving the attempted path.
 */
export function ProtectedRoute() {
  const phase = useAuthStore((s) => s.phase);
  const location = useLocation();

  if (phase === "idle") {
    return <LoadingScreen />;
  }

  if (phase === "unauthenticated") {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (phase === "totp_verify") {
    return <Navigate to="/auth/totp-verify" replace />;
  }

  if (phase === "totp_setup") {
    return <Navigate to="/auth/totp-setup" replace />;
  }

  // phase === "authenticated"
  return <Outlet />;
}
