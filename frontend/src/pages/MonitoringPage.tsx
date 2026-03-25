/**
 * Smart BI Agent — Monitoring & Admin Dashboard
 * Phase 6 | Session 8 | Admin only
 *
 * System health, audit logs, LLM token usage.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, Search, RefreshCw, Loader2, Database,
  Heart, AlertTriangle, CheckCircle2, Clock, Cpu,
  FileText, Filter,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input } from "@/components/ui";

type MonitorTab = "health" | "audit" | "tokens";

// ─── Health Dashboard ───────────────────────────────────────────────────────

function HealthPanel() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<Record<string, unknown>>("/../../health"),
    retry: 1,
  });

  const services = [
    { name: "API Server", status: data ? "healthy" : "unknown", detail: "FastAPI + Uvicorn" },
    { name: "PostgreSQL", status: data?.status === "ok" ? "healthy" : "degraded", detail: "App database" },
    { name: "Redis", status: data?.status === "ok" ? "healthy" : "degraded", detail: "Cache + security" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">System Health</h2>
        <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3 w-3" />} onClick={() => refetch()} isLoading={isLoading}>Refresh</Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {services.map((svc) => (
          <Card key={svc.name} className="p-4">
            <div className="flex items-center gap-3">
              <span className={cn("p-2 rounded-lg",
                svc.status === "healthy" ? "bg-emerald-500/10 text-emerald-400" :
                svc.status === "degraded" ? "bg-amber-500/10 text-amber-400" :
                "bg-slate-500/10 text-slate-400"
              )}>
                {svc.status === "healthy" ? <CheckCircle2 className="h-5 w-5" /> :
                 svc.status === "degraded" ? <AlertTriangle className="h-5 w-5" /> :
                 <Heart className="h-5 w-5" />}
              </span>
              <div>
                <p className="text-sm font-medium text-slate-200">{svc.name}</p>
                <p className="text-[10px] text-slate-500">{svc.detail}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-4">
        <h3 className="text-xs font-semibold text-slate-400 mb-3">System Info</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div><span className="text-slate-500">Status</span><p className="text-slate-200 font-medium mt-0.5">{String(data?.status || "checking…")}</p></div>
          <div><span className="text-slate-500">Version</span><p className="text-slate-200 font-medium mt-0.5">v3.1.0</p></div>
          <div><span className="text-slate-500">Environment</span><p className="text-slate-200 font-medium mt-0.5">Docker</p></div>
          <div><span className="text-slate-500">Workers</span><p className="text-slate-200 font-medium mt-0.5">4 (uvicorn)</p></div>
        </div>
      </Card>
    </div>
  );
}

// ─── Audit Log Viewer ───────────────────────────────────────────────────────

interface AuditEntry {
  id: string;
  user_id: string | null;
  execution_status: string;
  question: string;
  row_count: number | null;
  duration_ms: number | null;
  ip_address: string | null;
  created_at: string;
}

interface AuditLogResponse {
  logs: AuditEntry[];
  total: number;
  skip: number;
  limit: number;
}

function AuditPanel() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["audit-logs", search, statusFilter],
    queryFn: () => {
      let path = "/audit/?limit=50";
      if (search) path += `&search=${encodeURIComponent(search)}`;
      if (statusFilter) path += `&status=${encodeURIComponent(statusFilter)}`;
      return api.get<AuditLogResponse>(path);
    },
  });

  const logs = data?.logs ?? [];

  const statusColors: Record<string, string> = {
    "query.executed": "text-emerald-400",
    "export.generated": "text-blue-400",
    "export.blocked_restricted": "text-red-400",
    "saved_query.created": "text-cyan-400",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">Audit Logs</h2>
        <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3 w-3" />} onClick={() => refetch()} isLoading={isLoading}>Refresh</Button>
      </div>

      <div className="flex gap-3">
        <div className="flex-1">
          <Input placeholder="Search audit logs…" value={search} onChange={(e) => setSearch(e.target.value)} icon={<Search className="h-3.5 w-3.5" />} />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="h-10 rounded-lg border border-slate-600/80 bg-slate-800/60 text-slate-300 text-xs px-3 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500/40">
          <option value="">All statuses</option>
          <option value="query.executed">query.executed</option>
          <option value="export.generated">export.generated</option>
          <option value="saved_query.created">saved_query.created</option>
          <option value="notification_platform.tested">notification.tested</option>
        </select>
      </div>

      {isLoading && <Card className="p-8"><div className="flex items-center justify-center gap-3"><Loader2 className="h-5 w-5 text-blue-400 animate-spin" /><span className="text-sm text-slate-400">Loading…</span></div></Card>}

      {!isLoading && logs.length === 0 && (
        <Card className="p-8"><div className="text-center"><FileText className="h-6 w-6 text-slate-600 mx-auto mb-2" /><p className="text-sm text-slate-400">No audit logs found</p></div></Card>
      )}

      {logs.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10 bg-slate-800/95 backdrop-blur-sm border-b border-slate-700/40">
                <tr>
                  <th className="text-left px-3 py-2.5 text-[10px] font-semibold text-slate-400 uppercase">Time</th>
                  <th className="text-left px-3 py-2.5 text-[10px] font-semibold text-slate-400 uppercase">Status</th>
                  <th className="text-left px-3 py-2.5 text-[10px] font-semibold text-slate-400 uppercase">Action</th>
                  <th className="text-left px-3 py-2.5 text-[10px] font-semibold text-slate-400 uppercase">IP</th>
                  <th className="text-right px-3 py-2.5 text-[10px] font-semibold text-slate-400 uppercase">Rows</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/20">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-blue-500/5 transition-colors">
                    <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{new Date(log.created_at).toLocaleString()}</td>
                    <td className="px-3 py-2">
                      <span className={cn("font-mono", statusColors[log.execution_status] || "text-slate-400")}>{log.execution_status}</span>
                    </td>
                    <td className="px-3 py-2 text-slate-300 max-w-[300px] truncate">{log.question}</td>
                    <td className="px-3 py-2 text-slate-500 font-mono">{log.ip_address || "—"}</td>
                    <td className="px-3 py-2 text-right text-slate-400">{log.row_count ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data && <div className="px-3 py-2 border-t border-slate-700/30 text-[10px] text-slate-500">{data.total} total entries</div>}
        </Card>
      )}
    </div>
  );
}

// ─── Token Usage ────────────────────────────────────────────────────────────

function TokensPanel() {
  return (
    <div className="space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">LLM Token Usage</h2>
      <Card className="p-8">
        <div className="text-center">
          <Cpu className="h-8 w-8 text-slate-600 mx-auto mb-3" />
          <p className="text-sm text-slate-400">Token usage charts</p>
          <p className="text-xs text-slate-500 mt-1">
            Daily and weekly token consumption per provider will be displayed here.
            Data is collected from the llm_token_usage table.
          </p>
        </div>
      </Card>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function MonitoringPage() {
  const [activeTab, setActiveTab] = useState<MonitorTab>("health");

  const tabs: { id: MonitorTab; label: string; icon: React.ReactNode }[] = [
    { id: "health", label: "System Health", icon: <Heart className="h-3.5 w-3.5" /> },
    { id: "audit", label: "Audit Logs", icon: <FileText className="h-3.5 w-3.5" /> },
    { id: "tokens", label: "Token Usage", icon: <Cpu className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2"><Activity className="h-6 w-6 text-blue-400" />Monitoring</h1>
        <p className="text-sm text-slate-400 mt-1">System health, audit trail, and usage metrics</p>
      </div>

      <div className="flex border-b border-slate-700/40">
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={cn("flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 -mb-px transition-all",
              activeTab === tab.id ? "border-blue-500 text-blue-400" : "border-transparent text-slate-500 hover:text-slate-300")}>
            {tab.icon}{tab.label}
          </button>
        ))}
      </div>

      {activeTab === "health" && <HealthPanel />}
      {activeTab === "audit" && <AuditPanel />}
      {activeTab === "tokens" && <TokensPanel />}
    </div>
  );
}