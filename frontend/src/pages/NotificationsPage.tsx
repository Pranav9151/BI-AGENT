/**
 * Smart BI Agent — Notification Platforms Page
 * Phase 6 | Session 5 | Admin only
 *
 * CRUD for notification platforms with test connectivity.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell, Plus, Trash2, RefreshCw, Loader2, X, CheckCircle2,
  XCircle, Wifi, Mail, MessageSquare, Hash,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input, Select } from "@/components/ui";
import type {
  NotificationPlatform, NotificationPlatformListResponse,
  NotificationPlatformTestResponse, NotificationPlatformCreateRequest,
} from "@/types/notifications";

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  slack: <Hash className="h-4 w-4" />,
  email: <Mail className="h-4 w-4" />,
  teams: <MessageSquare className="h-4 w-4" />,
  webhook: <Wifi className="h-4 w-4" />,
};

const PLATFORM_COLORS: Record<string, string> = {
  slack: "text-purple-400 bg-purple-500/10 border-purple-500/20",
  email: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  teams: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
  webhook: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
};

function CreatePlatformModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [platformType, setPlatformType] = useState("slack");
  const [configJson, setConfigJson] = useState("");

  const createMutation = useMutation({
    mutationFn: (body: NotificationPlatformCreateRequest) =>
      api.post("/notifications/", body),
    onSuccess: () => { toast.success("Platform created"); onCreated(); onClose(); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const handleCreate = () => {
    if (!name.trim()) { toast.error("Name is required"); return; }
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configJson || "{}");
    } catch { toast.error("Invalid JSON config"); return; }
    createMutation.mutate({
      name: name.trim(), platform_type: platformType as any,
      delivery_config: config, is_active: true,
      is_inbound_enabled: false, is_outbound_enabled: true,
    });
  };

  const placeholder: Record<string, string> = {
    slack: '{"bot_token": "xoxb-...", "signing_secret": "..."}',
    email: '{"smtp_host": "smtp.gmail.com", "smtp_port": 587, "username": "...", "password": "..."}',
    teams: '{"webhook_url": "https://..."}',
    webhook: '{"url": "https://...", "secret": "..."}',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md glass-strong rounded-2xl shadow-2xl animate-page-in">
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Bell className="h-4 w-4 text-blue-400" />Add Notification Platform
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <Input label="Platform Name" placeholder="e.g. Production Slack" value={name} onChange={(e) => setName(e.target.value)} />
          <Select label="Platform Type" value={platformType} onChange={(e) => setPlatformType(e.target.value)}
            options={[
              { value: "slack", label: "Slack" }, { value: "email", label: "Email (SMTP)" },
              { value: "teams", label: "Microsoft Teams" }, { value: "webhook", label: "Webhook" },
            ]}
          />
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-slate-300">Delivery Config (JSON)</label>
            <textarea value={configJson} onChange={(e) => setConfigJson(e.target.value)}
              placeholder={placeholder[platformType] || '{}'}
              rows={4}
              className="w-full rounded-lg border border-slate-600/80 bg-slate-800/60 text-slate-100 text-xs font-mono placeholder:text-slate-500 px-3 py-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-colors"
            />
            <p className="text-[10px] text-slate-500">Credentials are encrypted at rest using HKDF.</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleCreate} isLoading={createMutation.isPending} disabled={!name.trim()}>Create</Button>
        </div>
      </div>
    </div>
  );
}

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<NotificationPlatformListResponse>("/notifications/"),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => api.post<NotificationPlatformTestResponse>(`/notifications/${id}/test`),
    onSuccess: (data) => {
      if (data.success) toast.success(data.message);
      else toast.error(data.message);
      setTestingId(null);
    },
    onError: (err: ApiRequestError) => { toast.error(err.message); setTestingId(null); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/notifications/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["notifications"] }); setDeletingId(null); toast.success("Platform deleted"); },
    onError: (err: ApiRequestError) => { toast.error(err.message); setDeletingId(null); },
  });

  const platforms = data?.platforms ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <span className="p-2 rounded-xl bg-gradient-to-br from-blue-500/20 to-indigo-500/10 border border-blue-500/15">
              <Bell className="h-5 w-5 text-blue-400" />
            </span>
            Notification Platforms
          </h1>
          <p className="text-sm text-slate-400 mt-1">Manage notification delivery channels</p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => refetch()} isLoading={isLoading}>Refresh</Button>
          <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setShowCreate(true)}>Add Platform</Button>
        </div>
      </div>

      {error && <Alert variant="error">{error instanceof ApiRequestError ? error.message : "Failed to load"}</Alert>}

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[1,2,3,4].map((i) => (
            <Card key={i} className="p-4"><div className="animate-skeleton rounded h-20 bg-slate-700/30" /></Card>
          ))}
        </div>
      )}

      {!isLoading && platforms.length === 0 && (
        <Card className="p-12">
          <div className="text-center">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/10 to-indigo-500/5 border border-blue-500/10 flex items-center justify-center mx-auto mb-4">
              <Bell className="h-8 w-8 text-slate-600" />
            </div>
            <p className="text-sm font-medium text-slate-300">No platforms configured</p>
            <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Add Slack, Email, Teams, or Webhook platforms to enable notification delivery.</p>
            <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setShowCreate(true)} className="mt-4">Add Platform</Button>
          </div>
        </Card>
      )}

      {platforms.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {platforms.map((p) => {
            const color = PLATFORM_COLORS[p.platform_type] || PLATFORM_COLORS.webhook;
            const icon = PLATFORM_ICONS[p.platform_type] || PLATFORM_ICONS.webhook;
            return (
              <Card key={p.platform_id} className="p-4">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className={cn("p-1.5 rounded-lg border", color)}>{icon}</span>
                    <div>
                      <h3 className="text-sm font-medium text-slate-200">{p.name}</h3>
                      <p className="text-[10px] text-slate-500 font-mono mt-0.5">{p.config_preview}</p>
                    </div>
                  </div>
                  <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border", p.is_active ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" : "text-red-400 bg-red-500/10 border-red-500/20")}>
                    {p.is_active ? "Active" : "Inactive"}
                  </span>
                </div>
                <div className="flex items-center justify-between pt-3 border-t border-slate-700/30">
                  <div className="flex items-center gap-2 text-[10px] text-slate-500">
                    <span className={cn("px-1.5 py-0.5 rounded border", color)}>{p.platform_type}</span>
                    {p.is_outbound_enabled && <span>Outbound</span>}
                    {p.is_inbound_enabled && <span>Inbound</span>}
                  </div>
                  <div className="flex items-center gap-0.5">
                    <button onClick={() => { setTestingId(p.platform_id); testMutation.mutate(p.platform_id); }}
                      disabled={testingId !== null}
                      className="p-1.5 rounded text-emerald-400 hover:bg-emerald-500/10 disabled:opacity-40 transition-colors" title="Test">
                      {testingId === p.platform_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                    </button>
                    {deletingId === p.platform_id ? (
                      <div className="flex items-center gap-1 ml-1">
                        <button onClick={() => deleteMutation.mutate(p.platform_id)} className="text-[10px] px-1.5 py-0.5 rounded bg-red-600/80 text-white hover:bg-red-500">Delete</button>
                        <button onClick={() => setDeletingId(null)} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">No</button>
                      </div>
                    ) : (
                      <button onClick={() => setDeletingId(p.platform_id)} className="p-1.5 rounded text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors" title="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {showCreate && <CreatePlatformModal onClose={() => setShowCreate(false)} onCreated={() => queryClient.invalidateQueries({ queryKey: ["notifications"] })} />}
    </div>
  );
}
