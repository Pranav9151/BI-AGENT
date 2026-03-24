/**
 * Smart BI Agent — Schema Browser Types
 * Phase 5 | Session 2
 * Maps to backend schemas/schema.py
 */

export interface ColumnInfo {
  type: string;
  nullable?: boolean | null;
  primary_key?: boolean | null;
}

export interface TableInfo {
  columns: Record<string, ColumnInfo>;
  row_count_estimate?: number | null;
}

export interface SchemaResponse {
  connection_id: string;
  schema_data: Record<string, TableInfo>;
  cached: boolean;
  cache_age_seconds?: number | null;
}

export interface SchemaRefreshResponse {
  connection_id: string;
  message: string;
  keys_deleted: number;
}