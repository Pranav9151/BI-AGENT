/**
 * Smart BI Agent — Schedules Page
 * Phase 6 | Session 6
 *
 * Schedule management with cron builder, timezone selector,
 * "Schedule This Query" from saved queries, run history.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Clock, Plus, Trash2, RefreshCw, Loader2, X, Play, Pause,
  Calendar, CheckCircle2, XCircle, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input, Select } from "@/components/ui";
import type { Schedule, ScheduleListResponse, ScheduleCreateRequest } from "@/types/schedules";
import type { SavedQueryListResponse } from "@/types/saved-queries";
import type { NotificationPlatformListResponse } from "@/types/notifications";

const STATUS_CONFIG: Record<string, { icon: React.ReactNode; color: string }> = {
  success: { icon: <CheckCircle2 className="h-3 w-3" />, color: "text-emerald-400" },
  failed: { icon: <XCircle className="h-3 w-3" />, color: "text-red-400" },
  skipped: { icon: <AlertTriangle className="h-3 w-3" />, color: "text-amber-400" },
  partial: { icon: <AlertTriangle className="h-3 w-3" />, color: "text-amber-400" },
};

const CRON_PRESETS = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Daily at 8 AM", value: "0 8 * * *" },
  { label: "Monday 9 AM", value: "0 9 * * 1" },
  { label: "Weekdays 7 AM", value: "0 7 * * 1-5" },
  { label: "1st of month", value: "0 9 1 * *" },
];

const TIMEZONES = [
  "UTC", "Asia/Riyadh", "Asia/Karachi", "Asia/Dubai",
  "Europe/London", "America/New_York", "America/Chicago", "America/Los_Angeles",
  "Asia/Kolkata", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney",
];

function CreateScheduleModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [savedQueryId, setSavedQueryId] = useState("");
  const [cronExpression, setCronExpression] = useState("0 8 * * *");
  const [timezone, setTimezone] = useState("Asia/Riyadh");
  const [outputFormat, setOutputFormat] = useState("csv");
  const [platformId, setPlatformId] = useState("");
  const [destination, setDestination] = useState("");

  const { data: sqData } = useQuery({
    queryKey: ["saved-queries"],
    queryFn: () => api.get<SavedQueryListResponse>("/saved-queries/?limit=200"),
  });

  const { data: platData } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<NotificationPlatformListResponse>("/notifications/"),
  });

  const queries = sqData?.queries ?? [];
  const platforms = platData?.platforms?.filter((p) => p.is_active) ?? [];

  const createMutation = useMutation({
    mutationFn: (body: ScheduleCreateRequest) => api.post("/schedules/", body),
    onSuccess: () => { toast.success("Schedule created"); onCreated(); onClose(); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const handleCreate = () => {
    if (!name.trim()) { toast.error("Name is required"); return; }
    if (!cronExpression.trim()) { toast.error("Cron expression is required"); return; }
    const targets = platformId && destination ? [{ platform_id: platformId, destination }] : [];
    createMutation.mutate({
      name: name.trim(), saved_query_id: savedQueryId || null,
      cron_expression: cronExpression.trim(), timezone,
      output_format: outputFormat, delivery_targets: targets, is_active: true,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg glass-strong rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto animate-page-in">
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Calendar className="h-4 w-4 text-blue-400" />Create Schedule
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <Input label="Schedule Name *" placeholder="e.g. Weekly Sales Report" value={name} onChange={(e) => setName(e.target.value)} />
          <Select label="Saved Query" value={savedQueryId} onChange={(e) => setSavedQueryId(e.target.value)}
            placeholder="Select a query to schedule…"
            options={queries.map((q) => ({ value: q.query_id, label: q.name }))}
          />
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Cron Expression *</label>
            <Input placeholder="0 8 * * 1" value={cronExpression} onChange={(e) => setCronExpression(e.target.value)}
              hint="5-field UNIX cron: minute hour day month weekday" />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {CRON_PRESETS.map((p) => (
                <button key={p.value} onClick={() => setCronExpression(p.value)}
                  className={cn("text-[10px] px-2 py-1 rounded-md border transition-colors",
                    cronExpression === p.value ? "border-blue-500/40 text-blue-400 bg-blue-500/10" : "border-slate-700 text-slate-500 hover:text-slate-300"
                  )}>{p.label}</button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Select label="Timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)}
              options={TIMEZONES.map((tz) => ({ value: tz, label: tz }))} />
            <Select label="Output Format" value={outputFormat} onChange={(e) => setOutputFormat(e.target.value)}
              options={[{ value: "csv", label: "CSV" }, { value: "excel", label: "Excel" }, { value: "pdf", label: "PDF" }]} />
          </div>
          <div className="rounded-lg border border-slate-700/40 p-3 space-y-3">
            <p className="text-xs font-medium text-slate-300">Delivery Target (optional)</p>
            <Select label="" value={platformId} onChange={(e) => setPlatformId(e.target.value)}
              placeholder="Select platform…"
              options={platforms.map((p) => ({ value: p.platform_id, label: `${p.name} (${p.platform_type})` }))} />
            {platformId && <Input placeholder="Channel, email, or webhook URL…" value={destination} onChange={(e) => setDestination(e.target.value)} />}
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleCreate} isLoading={createMutation.isPending} disabled={!name.trim()}>Create Schedule</Button>
        </div>
      </div>
    </div>
  );
}

export default function SchedulesPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => api.get<ScheduleListResponse>("/schedules/"),
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/schedules/${id}/toggle`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["schedules"] }); toast.success("Schedule toggled"); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/schedules/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["schedules"] }); setDeletingId(null); toast.success("Schedule deleted"); },
    onError: (err: ApiRequestError) => { toast.error(err.message); setDeletingId(null); },
  });

  const schedules = data?.schedules ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <span className="p-2 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10 border border-blue-500/15">
              <Clock className="h-5 w-5 text-blue-400" />
            </span>
            Scheduled Reports
          </h1>
          <p className="text-sm text-slate-400 mt-1">Automate query execution and delivery</p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => refetch()} isLoading={isLoading}>Refresh</Button>
          <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setShowCreate(true)}>New Schedule</Button>
        </div>
      </div>

      {error && <Alert variant="error">{error instanceof ApiRequestError ? error.message : "Failed to load"}</Alert>}
      {isLoading && (
        <div className="space-y-3">
          {[1,2,3].map((i) => (
            <Card key={i} className="p-4"><div className="animate-skeleton rounded h-16 bg-slate-700/30" /></Card>
          ))}
        </div>
      )}

      {!isLoading && schedules.length === 0 && (
        <Card className="p-12">
          <div className="text-center">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/10 to-cyan-500/5 border border-blue-500/10 flex items-center justify-center mx-auto mb-4">
              <Clock className="h-8 w-8 text-slate-600" />
            </div>
            <p className="text-sm font-medium text-slate-300">No schedules yet</p>
            <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Create a schedule to automate report execution and delivery to Slack, Email, or Teams.</p>
            <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setShowCreate(true)} className="mt-4">New Schedule</Button>
          </div>
        </Card>
      )}

      {schedules.length > 0 && (
        <div className="space-y-3">
          {schedules.map((s, idx) => {
            const statusCfg = STATUS_CONFIG[s.last_run_status || ""] || null;
            return (
              <Card key={s.schedule_id} className="p-4 animate-fade-in" style={{ animationDelay: `${Math.min(idx * 50, 300)}ms` }}>
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium text-slate-200">{s.name}</h3>
                      <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border",
                        s.is_active ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" : "text-slate-500 bg-slate-500/10 border-slate-600/30"
                      )}>{s.is_active ? "Active" : "Paused"}</span>
                    </div>
                    <div className="flex items-center gap-4 mt-1.5 text-xs text-slate-500">
                      <span className="font-mono bg-slate-700/40 px-1.5 py-0.5 rounded">{s.cron_expression}</span>
                      <span>{s.timezone}</span>
                      <span className="uppercase text-[10px]">{s.output_format}</span>
                      {s.delivery_targets.length > 0 && <span>{s.delivery_targets.length} target{s.delivery_targets.length !== 1 ? "s" : ""}</span>}
                    </div>
                    {statusCfg && s.last_run_at && (
                      <div className={cn("flex items-center gap-1.5 mt-2 text-xs", statusCfg.color)}>
                        {statusCfg.icon}
                        <span>Last: {s.last_run_status} · {new Date(s.last_run_at).toLocaleString()}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-0.5 shrink-0 ml-3">
                    <button onClick={() => toggleMutation.mutate(s.schedule_id)}
                      className={cn("p-1.5 rounded transition-colors", s.is_active ? "text-amber-400 hover:bg-amber-500/10" : "text-emerald-400 hover:bg-emerald-500/10")}
                      title={s.is_active ? "Pause" : "Resume"}>
                      {s.is_active ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                    </button>
                    {deletingId === s.schedule_id ? (
                      <div className="flex items-center gap-1 ml-1">
                        <button onClick={() => deleteMutation.mutate(s.schedule_id)} className="text-[10px] px-1.5 py-0.5 rounded bg-red-600/80 text-white hover:bg-red-500">Delete</button>
                        <button onClick={() => setDeletingId(null)} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">No</button>
                      </div>
                    ) : (
                      <button onClick={() => setDeletingId(s.schedule_id)} className="p-1.5 rounded text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors" title="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {showCreate && <CreateScheduleModal onClose={() => setShowCreate(false)} onCreated={() => queryClient.invalidateQueries({ queryKey: ["schedules"] })} />}
    </div>
  );
}
