/**
 * Smart BI Agent — Alerts Page (Phase 12)
 * Threshold-based alerting: define rules, get notified.
 *
 * Features:
 *   - Create alert rules with SQL metric queries
 *   - Configure thresholds (gt, lt, eq, etc.)
 *   - Set notification channels (email, Slack, webhook)
 *   - View alert history (firings)
 *   - Test alerts without sending notifications
 *   - Enable/disable toggle
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell, Plus, Trash2, Edit3, Play, Pause,
  AlertTriangle, CheckCircle2, Clock, Zap,
  Mail, MessageSquare, Globe, Loader2,
  ChevronDown, ChevronRight, X, Send,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Input, Alert } from "@/components/ui";

// ─── Types ───────────────────────────────────────────────────────────────────

interface AlertChannel {
  type: string;
  target: string;
  label: string;
}

interface AlertCondition {
  metric_sql: string;
  operator: string;
  threshold: number;
  connection_id: string;
}

interface AlertRule {
  alert_id: string;
  name: string;
  description: string;
  condition: AlertCondition;
  channels: AlertChannel[];
  check_interval_minutes: number;
  cooldown_minutes: number;
  enabled: boolean;
  severity: string;
  last_evaluated: string | null;
  last_fired: string | null;
  fire_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

const OPERATORS = [
  { value: "gt", label: "> greater than" },
  { value: "gte", label: ">= greater or equal" },
  { value: "lt", label: "< less than" },
  { value: "lte", label: "<= less or equal" },
  { value: "eq", label: "= equals" },
  { value: "neq", label: "!= not equals" },
];

const SEVERITIES = [
  { value: "info", label: "Info", color: "text-blue-400 bg-blue-500/10" },
  { value: "warning", label: "Warning", color: "text-amber-400 bg-amber-500/10" },
  { value: "critical", label: "Critical", color: "text-red-400 bg-red-500/10" },
];

const CHANNEL_ICONS: Record<string, React.ReactNode> = {
  email: <Mail className="h-3.5 w-3.5" />,
  slack: <MessageSquare className="h-3.5 w-3.5" />,
  webhook: <Globe className="h-3.5 w-3.5" />,
};

// ─── Alert Card ──────────────────────────────────────────────────────────────

function AlertCard({
  alert,
  onEdit,
  onDelete,
  onToggle,
}: {
  alert: AlertRule;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  const severity = SEVERITIES.find((s) => s.value === alert.severity);
  const op = OPERATORS.find((o) => o.value === alert.condition.operator);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Status indicator */}
        <div
          className={cn(
            "w-2 h-2 rounded-full shrink-0",
            alert.status === "firing"
              ? "bg-red-500 animate-pulse"
              : alert.enabled
                ? "bg-emerald-500"
                : "bg-slate-600"
          )}
        />

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-white truncate">
              {alert.name}
            </h3>
            <span
              className={cn(
                "text-[9px] font-semibold px-1.5 py-0.5 rounded",
                severity?.color
              )}
            >
              {severity?.label}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-0.5 truncate">
            When result {op?.label || alert.condition.operator}{" "}
            {alert.condition.threshold.toLocaleString()}
          </p>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4 shrink-0">
          {alert.fire_count > 0 && (
            <div className="text-center">
              <p className="text-sm font-bold text-amber-400">
                {alert.fire_count}
              </p>
              <p className="text-[8px] text-slate-600 uppercase">Firings</p>
            </div>
          )}
          <div className="text-center">
            <p className="text-[10px] text-slate-500">
              Every {alert.check_interval_minutes}m
            </p>
          </div>
        </div>

        {/* Channels */}
        <div className="flex items-center gap-1 shrink-0">
          {alert.channels.map((ch, i) => (
            <span
              key={i}
              className="p-1 rounded bg-slate-800/40 text-slate-500"
              title={`${ch.type}: ${ch.target}`}
            >
              {CHANNEL_ICONS[ch.type] || <Bell className="h-3.5 w-3.5" />}
            </span>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onToggle}
            className={cn(
              "p-1.5 rounded-lg transition-colors",
              alert.enabled
                ? "text-emerald-400 hover:bg-emerald-500/10"
                : "text-slate-600 hover:bg-slate-700/30"
            )}
            title={alert.enabled ? "Disable" : "Enable"}
          >
            {alert.enabled ? (
              <Zap className="h-3.5 w-3.5" />
            ) : (
              <Pause className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            onClick={onEdit}
            className="p-1.5 rounded-lg text-slate-500 hover:text-blue-400 hover:bg-blue-500/10 transition-colors"
          >
            <Edit3 className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </Card>
  );
}

// ─── Create/Edit Form ────────────────────────────────────────────────────────

function AlertForm({
  onSubmit,
  onCancel,
  initial,
  connections,
}: {
  onSubmit: (data: any) => void;
  onCancel: () => void;
  initial?: AlertRule | null;
  connections: { connection_id: string; name: string }[];
}) {
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [metricSql, setMetricSql] = useState(initial?.condition.metric_sql || "SELECT COUNT(*) FROM ");
  const [operator, setOperator] = useState(initial?.condition.operator || "gt");
  const [threshold, setThreshold] = useState(String(initial?.condition.threshold ?? "100"));
  const [connectionId, setConnectionId] = useState(initial?.condition.connection_id || connections[0]?.connection_id || "");
  const [severity, setSeverity] = useState(initial?.severity || "warning");
  const [interval, setInterval] = useState(String(initial?.check_interval_minutes ?? "60"));
  const [channelType, setChannelType] = useState("email");
  const [channelTarget, setChannelTarget] = useState("");
  const [channels, setChannels] = useState<AlertChannel[]>(initial?.channels || []);

  const addChannel = () => {
    if (!channelTarget.trim()) return;
    setChannels([...channels, { type: channelType, target: channelTarget.trim(), label: channelTarget.trim() }]);
    setChannelTarget("");
  };

  const handleSubmit = () => {
    if (!name.trim() || !metricSql.trim()) {
      toast.error("Name and metric SQL are required");
      return;
    }
    onSubmit({
      name: name.trim(),
      description: description.trim(),
      condition: {
        metric_sql: metricSql.trim(),
        operator,
        threshold: parseFloat(threshold) || 0,
        connection_id: connectionId,
      },
      channels,
      check_interval_minutes: parseInt(interval) || 60,
      cooldown_minutes: 60,
      severity,
      enabled: true,
    });
  };

  return (
    <Card className="overflow-hidden">
      <div className="px-4 py-3 bg-slate-800/30 border-b border-slate-700/20">
        <h3 className="text-sm font-semibold text-white">
          {initial ? "Edit Alert" : "New Alert Rule"}
        </h3>
      </div>
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Revenue Drop Alert"
              className="w-full h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-sm text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30" />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Connection</label>
            <select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}
              className="w-full h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-sm text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30">
              {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Metric SQL (must return a single number)</label>
          <textarea value={metricSql} onChange={(e) => setMetricSql(e.target.value)} rows={3}
            className="w-full rounded-lg border border-slate-700/40 bg-slate-800/30 text-xs text-slate-300 px-3 py-2 font-mono focus:outline-none focus:ring-1 focus:ring-blue-500/30" />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Operator</label>
            <select value={operator} onChange={(e) => setOperator(e.target.value)}
              className="w-full h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-sm text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30">
              {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Threshold</label>
            <input type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)}
              className="w-full h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-sm text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30" />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Severity</label>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}
              className="w-full h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-sm text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30">
              {SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Check Interval (minutes)</label>
          <input type="number" value={interval} onChange={(e) => setInterval(e.target.value)} min={5} max={1440}
            className="w-32 h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-sm text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30" />
        </div>

        {/* Channels */}
        <div>
          <label className="text-[10px] text-slate-500 uppercase font-semibold mb-1 block">Notification Channels</label>
          <div className="flex items-center gap-2 mb-2">
            <select value={channelType} onChange={(e) => setChannelType(e.target.value)}
              className="h-8 rounded-lg border border-slate-700/40 bg-slate-800/30 text-xs text-slate-300 px-2 focus:outline-none">
              <option value="email">Email</option>
              <option value="slack">Slack</option>
              <option value="webhook">Webhook</option>
            </select>
            <input value={channelTarget} onChange={(e) => setChannelTarget(e.target.value)}
              placeholder={channelType === "email" ? "user@company.com" : channelType === "slack" ? "https://hooks.slack.com/..." : "https://api.example.com/alert"}
              onKeyDown={(e) => { if (e.key === "Enter") addChannel(); }}
              className="flex-1 h-8 rounded-lg border border-slate-700/40 bg-slate-800/30 text-xs text-slate-300 px-3 focus:outline-none focus:ring-1 focus:ring-blue-500/30" />
            <Button size="sm" variant="ghost" onClick={addChannel} className="h-8 text-[10px]">Add</Button>
          </div>
          {channels.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {channels.map((ch, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-slate-800/40 text-[10px] text-slate-400 border border-slate-700/30">
                  {CHANNEL_ICONS[ch.type]}{ch.target}
                  <button onClick={() => setChannels(channels.filter((_, j) => j !== i))} className="hover:text-red-400"><X className="h-2.5 w-2.5" /></button>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-slate-700/20">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button size="sm" onClick={handleSubmit} icon={<Bell className="h-3.5 w-3.5" />}>
            {initial ? "Update Alert" : "Create Alert"}
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingAlert, setEditingAlert] = useState<AlertRule | null>(null);

  // Data
  const { data: alertsData, isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.get<{ alerts: AlertRule[]; total: number }>("/alerts/"),
  });

  const { data: connData } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<{ connections: { connection_id: string; name: string; is_active: boolean }[] }>("/connections/"),
  });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: any) => api.post("/alerts/", data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["alerts"] }); setShowForm(false); toast.success("Alert created"); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => api.put(`/alerts/${id}`, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["alerts"] }); setEditingAlert(null); toast.success("Alert updated"); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.delete(`/alerts/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["alerts"] }); toast.success("Alert deleted"); },
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.put(`/alerts/${id}`, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const alerts = alertsData?.alerts ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Bell className="h-6 w-6 text-amber-400" />
            Alerts
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Set up threshold-based alerts on your metrics
          </p>
        </div>
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => { setShowForm(true); setEditingAlert(null); }}>
          New Alert
        </Button>
      </div>

      {/* Create/Edit Form */}
      {(showForm || editingAlert) && (
        <AlertForm
          initial={editingAlert}
          connections={connections}
          onSubmit={(data) => {
            if (editingAlert) {
              updateMut.mutate({ id: editingAlert.alert_id, data });
            } else {
              createMut.mutate(data);
            }
          }}
          onCancel={() => { setShowForm(false); setEditingAlert(null); }}
        />
      )}

      {/* Loading */}
      {isLoading && (
        <Card className="p-12">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
            <span className="text-sm text-slate-400">Loading alerts…</span>
          </div>
        </Card>
      )}

      {/* Empty */}
      {!isLoading && alerts.length === 0 && !showForm && (
        <Card className="p-12">
          <div className="text-center">
            <Bell className="h-10 w-10 text-slate-600 mx-auto mb-3" />
            <p className="text-sm text-slate-400 font-medium">No alerts configured</p>
            <p className="text-xs text-slate-500 mt-1">
              Create alert rules to get notified when metrics cross thresholds
            </p>
          </div>
        </Card>
      )}

      {/* Alert List */}
      {alerts.length > 0 && (
        <div className="space-y-2">
          {alerts.map((alert) => (
            <AlertCard
              key={alert.alert_id}
              alert={alert}
              onEdit={() => { setEditingAlert(alert); setShowForm(false); }}
              onDelete={() => deleteMut.mutate(alert.alert_id)}
              onToggle={() => toggleMut.mutate({ id: alert.alert_id, enabled: !alert.enabled })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
