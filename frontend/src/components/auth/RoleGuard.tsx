import React from "react";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Roles hierarchy (highest → lowest):
 *   ceo > admin > analyst > viewer
 *
 * CEO has full system-wide access. Admin controls operations.
 * Analyst can query and build. Viewer is read-only.
 */
export type Role = "viewer" | "analyst" | "admin" | "ceo";

interface RoleGuardProps {
  /** Minimum role required (inclusive). ceo > admin > analyst > viewer */
  minRole?: Role;
  /** Specific roles allowed */
  allowedRoles?: Role[];
  /** Content to show if access denied */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export const ROLE_LEVEL: Record<Role, number> = {
  viewer: 0,
  analyst: 1,
  admin: 2,
  ceo: 3,
};

/**
 * Conditional renderer based on the current user's role.
 *
 * Usage:
 *   <RoleGuard minRole="admin">
 *     <AdminPanel />
 *   </RoleGuard>
 *
 *   <RoleGuard allowedRoles={["analyst", "admin", "ceo"]}>
 *     <QueryEditor />
 *   </RoleGuard>
 *
 * NOTE: minRole="admin" also allows CEO users automatically (ceo level > admin level).
 */
export function RoleGuard({
  minRole,
  allowedRoles,
  fallback = null,
  children,
}: RoleGuardProps) {
  const role = useAuthStore((s) => s.user?.role) as Role | undefined;

  if (!role) return <>{fallback}</>;

  if (allowedRoles && !allowedRoles.includes(role)) {
    return <>{fallback}</>;
  }

  if (minRole) {
    const userLevel = ROLE_LEVEL[role] ?? 0;
    const requiredLevel = ROLE_LEVEL[minRole] ?? 0;
    if (userLevel < requiredLevel) {
      return <>{fallback}</>;
    }
  }

  return <>{children}</>;
}
