/**
 * Smart BI Agent — Notification Platform Types
 * Phase 6 | Maps to backend schemas/notification.py
 */

export type PlatformType = "slack" | "teams" | "whatsapp" | "jira" | "clickup" | "webhook" | "email";

export interface NotificationPlatformCreateRequest {
  name: string;
  platform_type: PlatformType;
  delivery_config: Record<string, unknown>;
  is_active: boolean;
  is_inbound_enabled: boolean;
  is_outbound_enabled: boolean;
}

export interface NotificationPlatform {
  platform_id: string;
  name: string;
  platform_type: string;
  config_preview: string;
  is_active: boolean;
  is_inbound_enabled: boolean;
  is_outbound_enabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationPlatformListResponse {
  platforms: NotificationPlatform[];
  total: number;
  skip: number;
  limit: number;
}

export interface NotificationPlatformTestResponse {
  platform_id: string;
  name: string;
  platform_type: string;
  success: boolean;
  message: string;
}