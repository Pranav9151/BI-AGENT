/**
 * Smart BI Agent — LLM Provider Types
 * Maps 1:1 to backend Pydantic schemas in app/schemas/llm_provider.py
 */

// ─── Enums ──────────────────────────────────────────────────────────────────

export type ProviderType =
  | "openai"
  | "claude"
  | "gemini"
  | "groq"
  | "deepseek"
  | "ollama";

export type DataResidency = "us" | "eu" | "cn" | "local" | "unknown";

// ─── Request ────────────────────────────────────────────────────────────────

export interface LLMProviderCreateRequest {
  name: string;
  provider_type: ProviderType;
  api_key?: string | null;
  base_url?: string | null;
  model_sql: string;
  model_insight?: string | null;
  model_suggestion?: string | null;
  max_tokens_sql: number;
  max_tokens_insight: number;
  temperature_sql: number;
  temperature_insight: number;
  is_active: boolean;
  is_default: boolean;
  priority: number;
  daily_token_budget: number;
  data_residency: DataResidency;
}

export interface LLMProviderUpdateRequest {
  name?: string;
  api_key?: string | null;
  base_url?: string | null;
  model_sql?: string;
  model_insight?: string | null;
  model_suggestion?: string | null;
  max_tokens_sql?: number;
  max_tokens_insight?: number;
  temperature_sql?: number;
  temperature_insight?: number;
  is_active?: boolean;
  is_default?: boolean;
  priority?: number;
  daily_token_budget?: number;
  data_residency?: DataResidency;
}

// ─── Response ───────────────────────────────────────────────────────────────

export interface LLMProvider {
  provider_id: string;
  name: string;
  provider_type: string;
  key_prefix: string | null;
  base_url: string | null;
  model_sql: string;
  model_insight: string | null;
  model_suggestion: string | null;
  max_tokens_sql: number;
  max_tokens_insight: number;
  temperature_sql: number;
  temperature_insight: number;
  is_active: boolean;
  is_default: boolean;
  priority: number;
  daily_token_budget: number;
  data_residency: string;
  created_by: string | null;
}

export interface LLMProviderListResponse {
  providers: LLMProvider[];
  total: number;
  skip: number;
  limit: number;
}

export interface LLMProviderTestResponse {
  success: boolean;
  provider_type: string;
  model_used: string;
  latency_ms: number | null;
  error: string | null;
}

export interface LLMProviderSetDefaultResponse {
  provider_id: string;
  name: string;
  is_default: boolean;
  message: string;
}

// ─── Model Registry ─────────────────────────────────────────────────────────

export interface ProviderModelEntry {
  model_id: string;
  use_case: string;
  is_default: boolean;
}

export interface ProviderModelsResponse {
  providers: Record<string, ProviderModelEntry[]>;
}
