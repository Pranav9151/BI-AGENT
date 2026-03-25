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