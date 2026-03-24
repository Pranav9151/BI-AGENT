/**
 * Smart BI Agent — User Management Types (Admin)
 * Maps to backend Pydantic schemas in app/schemas/user.py
 */

export type UserRole = "viewer" | "analyst" | "admin";

export interface UserCreateRequest {
  email: string;
  name: string;
  password: string;
  role: UserRole;
  department?: string | null;
}

export interface UserUpdateRequest {
  name?: string;
  department?: string | null;
  role?: UserRole;
  is_active?: boolean;
  is_approved?: boolean;
}

export interface UserAdmin {
  user_id: string;
  email: string;
  name: string;
  role: string;
  department: string | null;
  is_active: boolean;
  is_approved: boolean;
  totp_enabled: boolean;
  last_login_at: string | null;
  created_at: string | null;
}

export interface UserListResponse {
  users: UserAdmin[];
  meta: {
    total: number;
    skip: number;
    limit: number;
    has_more: boolean;
  };
}
