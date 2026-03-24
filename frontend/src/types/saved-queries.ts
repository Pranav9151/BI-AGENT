/**
 * Smart BI Agent — Saved Query Types
 * Maps 1:1 to backend Pydantic schemas in app/schemas/saved_query.py
 */

export type SensitivityLevel = "normal" | "sensitive" | "restricted";

export interface SavedQueryCreateRequest {
  connection_id: string;
  name: string;
  description?: string | null;
  question: string;
  sql_query: string;
  tags: string[];
  sensitivity: SensitivityLevel;
  is_shared: boolean;
  is_pinned: boolean;
}

export interface SavedQueryUpdateRequest {
  name?: string;
  description?: string | null;
  question?: string;
  sql_query?: string;
  tags?: string[];
  sensitivity?: SensitivityLevel;
  is_shared?: boolean;
  is_pinned?: boolean;
}

export interface SavedQuery {
  query_id: string;
  user_id: string;
  connection_id: string;
  name: string;
  description: string | null;
  question: string;
  sql_query: string;
  tags: string[];
  sensitivity: string;
  is_shared: boolean;
  is_pinned: boolean;
  run_count: number;
  last_run_at: string | null;
}

export interface SavedQueryListResponse {
  queries: SavedQuery[];
  total: number;
  skip: number;
  limit: number;
}
