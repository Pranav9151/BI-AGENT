/**
 * Smart BI Agent — Auth Types
 * Maps 1:1 to backend Pydantic schemas in app/schemas/auth.py + user.py
 */

// ─── Login ───────────────────────────────────────────────────────────────────

export interface LoginRequest {
  email: string;
  password: string;
}

/**
 * POST /api/v1/auth/login response.
 *
 * Three possible client states:
 *   1. Full access: totp_required=false → access_token is full-scope JWT
 *   2. TOTP verify:  totp_required=true, totp_setup_required=false → pre_totp JWT
 *   3. TOTP setup:   totp_required=true, totp_setup_required=true  → pre_totp JWT
 */
export interface LoginResponse {
  access_token: string;
  token_type: string;
  totp_required: boolean;
  totp_setup_required: boolean;
}

// ─── TOTP ────────────────────────────────────────────────────────────────────

export interface TOTPVerifyRequest {
  code: string;
}

export interface TOTPVerifyResponse {
  access_token: string;
  token_type: string;
}

export interface TOTPSetupResponse {
  qr_code: string;   // data:image/png;base64,...
  secret: string;    // Base32 for manual entry
  uri: string;       // otpauth:// URI
}

export interface TOTPConfirmRequest {
  code: string;
}

export interface TOTPConfirmResponse {
  message: string;
}

// ─── Token Refresh ───────────────────────────────────────────────────────────

export interface RefreshResponse {
  access_token: string;
  token_type: string;
}

// ─── Current User ────────────────────────────────────────────────────────────

export interface User {
  user_id: string;
  email: string;
  name: string;
  role: "viewer" | "analyst" | "admin";
  department: string | null;
  totp_enabled: boolean;
  is_active: boolean;
  is_approved: boolean;
  last_login_at: string | null;
}

// ─── API Error Envelope ──────────────────────────────────────────────────────

export interface ApiError {
  error: {
    code: string;
    message: string;
    request_id?: string;
    fields?: Array<{ field: string; issue: string }>;
  };
}

// ─── User Update ─────────────────────────────────────────────────────────────

export interface UserUpdateRequest {
  name?: string;
  department?: string | null;
}
