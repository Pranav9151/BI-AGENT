/**
 * Smart BI Agent — Connection Types
 * Maps 1:1 to backend Pydantic schemas in app/schemas/connection.py
 */

// ─── Enums ──────────────────────────────────────────────────────────────────

export type DBType = "postgresql" | "mysql" | "mssql" | "bigquery" | "snowflake";

export type SSLMode =
  | "disable"
  | "allow"
  | "prefer"
  | "require"
  | "verify-ca"
  | "verify-full";

// ─── Request ────────────────────────────────────────────────────────────────

export interface ConnectionCreateRequest {
  name: string;
  db_type: DBType;
  host: string;
  port: number;
  database_name: string;
  username: string;
  password: string;
  ssl_mode: SSLMode;
  query_timeout: number;
  max_rows: number;
  allowed_schemas: string[];
}

export interface ConnectionUpdateRequest {
  name?: string;
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  password?: string;
  ssl_mode?: SSLMode;
  query_timeout?: number;
  max_rows?: number;
  allowed_schemas?: string[];
  is_active?: boolean;
}

// ─── Response ───────────────────────────────────────────────────────────────

export interface Connection {
  connection_id: string;
  name: string;
  db_type: string;
  host: string | null;
  port: number | null;
  database_name: string | null;
  ssl_mode: string;
  query_timeout: number;
  max_rows: number;
  allowed_schemas: string[] | null;
  is_active: boolean;
  created_by: string | null;
}

export interface ConnectionListResponse {
  connections: Connection[];
  total: number;
  skip: number;
  limit: number;
}

export interface ConnectionTestResponse {
  success: boolean;
  latency_ms: number | null;
  error: string | null;
  resolved_ip: string | null;
}
