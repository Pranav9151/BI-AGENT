/**
 * Smart BI Agent — Permission Types
 * Phase 6 | Maps to backend schemas/permission.py
 */

export interface RolePermission {
  permission_id: string;
  role: string;
  connection_id: string;
  allowed_tables: string[];
  denied_columns: string[];
  created_at: string | null;
}

export interface DepartmentPermission {
  permission_id: string;
  department: string;
  connection_id: string;
  allowed_tables: string[];
  denied_columns: string[];
  created_at: string | null;
}

export interface UserPermission {
  permission_id: string;
  user_id: string;
  connection_id: string;
  allowed_tables: string[];
  denied_tables: string[];
  denied_columns: string[];
  created_at: string | null;
}

export interface RolePermissionListResponse {
  permissions: RolePermission[];
  total: number;
}

export interface DepartmentPermissionListResponse {
  permissions: DepartmentPermission[];
  total: number;
}

export interface UserPermissionListResponse {
  permissions: UserPermission[];
  total: number;
}