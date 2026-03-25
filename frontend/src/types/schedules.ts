/**
 * Smart BI Agent — Schedule Types
 * Phase 6 | Maps to backend schemas/schedule.py
 */

export interface DeliveryTarget {
  platform_id: string;
  destination: string;
}

export interface ScheduleCreateRequest {
  name: string;
  saved_query_id?: string | null;
  cron_expression: string;
  timezone: string;
  output_format: string;
  delivery_targets: DeliveryTarget[];
  is_active: boolean;
}

export interface Schedule {
  schedule_id: string;
  user_id: string;
  saved_query_id: string | null;
  name: string;
  cron_expression: string;
  timezone: string;
  output_format: string;
  delivery_targets: DeliveryTarget[];
  is_active: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleListResponse {
  schedules: Schedule[];
  total: number;
  skip: number;
  limit: number;
}