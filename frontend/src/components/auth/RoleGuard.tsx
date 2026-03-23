import React from "react";
import { useAuthStore } from "@/stores/auth-store";

type Role = "viewer" | "analyst" | "admin";

interface RoleGuardProps {
  /** Minimum role required (inclusive: admin > analyst > viewer) */
  minRole?: Role;
  /** Specific roles allowed */
  allowedRoles?: Role[];
  /** Content to show if access denied */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

const ROLE_LEVEL: Record<Role, number> = {
  viewer: 0,
  analyst: 1,
  admin: 2,
};

/**
 * Conditional renderer based on the current user's role.
 *
 * Usage:
 *   <RoleGuard minRole="admin">
 *     <AdminPanel />
 *   </RoleGuard>
 *
 *   <RoleGuard allowedRoles={["analyst", "admin"]}>
 *     <QueryEditor />
 *   </RoleGuard>
 */
export function RoleGuard({
  minRole,
  allowedRoles,
  fallback = null,
  children,
}: RoleGuardProps) {
  const role = useAuthStore((s) => s.user?.role);

  if (!role) return <>{fallback}</>;

  if (allowedRoles && !allowedRoles.includes(role)) {
    return <>{fallback}</>;
  }

  if (minRole && ROLE_LEVEL[role] < ROLE_LEVEL[minRole]) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}
