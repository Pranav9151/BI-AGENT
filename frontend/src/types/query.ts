/**
 * Smart BI Agent — Query Types
 * Maps to routes_query.py QueryRequest/QueryResponse
 */

export interface QueryRequest {
  question: string;
  connection_id: string;
  conversation_id?: string | null;
}

export interface QueryResponse {
  question: string;
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  duration_ms: number;
  truncated: boolean;
  conversation_id: string;
  message_id: string;
  provider_type: string;
  model: string;
  llm_latency_ms: number;
  insight: string | null;
}

export interface SuggestionCategory {
  key: string;
  label: string;
  icon: string;
  color: string;
  questions: string[];
}

export interface SuggestionsResponse {
  connection_id: string;
  categories: SuggestionCategory[];
}

// ─── Structured Query (Phase 12) ─────────────────────────────────────────────

export interface StructuredFieldSpec {
  table: string;
  column: string;
  type: string;
  agg: string;
}

export interface StructuredFilterSpec {
  table: string;
  column: string;
  operator: string;
  value?: unknown;
  values?: unknown[];
}

export interface StructuredQueryRequest {
  connection_id: string;
  dimensions: StructuredFieldSpec[];
  measures: StructuredFieldSpec[];
  filters: StructuredFilterSpec[];
  order_by?: string | null;
  order_dir?: string;
  limit?: number;
}

export interface StructuredQueryResponse {
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  duration_ms: number;
  truncated: boolean;
  tables_used: string[];
  joins_generated: string[];
}