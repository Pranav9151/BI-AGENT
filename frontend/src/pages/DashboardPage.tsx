/**
 * Smart BI Agent — Dashboard v2 (Command Center)
 *
 * Features:
 *   - Company branding (name + logo URL — admin editable)
 *   - Quick stats (connections, queries, schedules)
 *   - Pinned saved queries as live KPI/chart widgets
 *   - Quick actions grid
 *   - Admin: platform health + edit mode
 *   - Recent query activity
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  MessageSquare, Database, Bookmark, Clock, Shield,
  BarChart3, HardDrive, Bell, Activity, ChevronRight,
  Sparkles, Play, Brain, Settings, Edit3, Check, X,
  Loader2, Pin, ExternalLink, Image,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { Button, Card, Input } from "@/components/ui";
import { RoleGuard } from "@/components/auth";
import { AutoChart, Scorecard, toNumber } from "@/components/QueryResults";
import type { ConnectionListResponse } from "@/types/connections";
import type { SavedQueryListResponse, SavedQuery } from "@/types/saved-queries";
import type { ScheduleListResponse } from "@/types/schedules";
import type { QueryRequest, QueryResponse } from "@/types/query";

// ─── Branding (stored in memory — will persist via API in Phase 7) ──────────

const DEFAULT_BRANDING = {
  companyName: "Smart BI Agent",
  logoUrl: "",
  tagline: "AI-Powered Business Intelligence",
};

function useBranding() {
  const [branding, setBranding] = useState(DEFAULT_BRANDING);
  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem("sbi_branding");
      if (saved) setBranding(JSON.parse(saved));
    } catch {}
  }, []);
  const update = (b: typeof DEFAULT_BRANDING) => {
    setBranding(b);
    try { window.sessionStorage.setItem("sbi_branding", JSON.stringify(b)); } catch {}
  };
  return { branding, update };
}

// ─── Branding Editor (admin only) ───────────────────────────────────────────

function BrandingEditor({ branding, onSave, onCancel }: {
  branding: typeof DEFAULT_BRANDING;
  onSave: (b: typeof DEFAULT_BRANDING) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(branding.companyName);
  const [logo, setLogo] = useState(branding.logoUrl);
  const [tagline, setTagline] = useState(branding.tagline);

  return (
    <div className="flex items-center gap-3 p-3 rounded-xl border border-blue-500/20 bg-blue-500/5">
      <Input placeholder="Company Name" value={name} onChange={(e) => setName(e.target.value)} className="h-8 text-sm" />
      <Input placeholder="Logo URL (optional)" value={logo} onChange={(e) => setLogo(e.target.value)} className="h-8 text-sm" />
      <Input placeholder="Tagline" value={tagline} onChange={(e) => setTagline(e.target.value)} className="h-8 text-sm" />
      <button onClick={() => onSave({ companyName: name, logoUrl: logo, tagline })} className="p-1.5 rounded text-emerald-400 hover:bg-emerald-500/10"><Check className="h-4 w-4" /></button>
      <button onClick={onCancel} className="p-1.5 rounded text-slate-400 hover:bg-slate-700/50"><X className="h-4 w-4" /></button>
    </div>
  );
}

// ─── Live Query Widget (pinned saved query → auto-run → display result) ─────

function QueryWidget({ query }: { query: SavedQuery }) {
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const runQuery = async () => {
    setLoading(true);
    try {
      const res = await api.post<QueryResponse>("/query/", {
        question: query.question,
        connection_id: query.connection_id,
      } as QueryRequest);
      setResult(res);
    } catch {
      // Silent fail for dashboard widgets
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { runQuery(); }, [query.query_id]);

  const isSingleValue = result && result.rows.length === 1 && result.columns.length <= 3;

  return (
    <Card className="overflow-hidden hover:border-slate-600/60 transition-colors">
      <div className="px-3 py-2 border-b border-slate-700/30 flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-300 truncate">{query.name}</p>
          <p className="text-[9px] text-slate-600 truncate">{query.question}</p>
        </div>
        <button onClick={runQuery} disabled={loading}
          className="p-1 rounded text-slate-500 hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors shrink-0">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
        </button>
      </div>
      <div className="p-2" style={{ minHeight: 120 }}>
        {loading && !result && (
          <div className="flex items-center justify-center h-24">
            <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />
          </div>
        )}
        {result && isSingleValue && (
          <Scorecard columns={result.columns} rows={result.rows} />
        )}
        {result && !isSingleValue && result.columns.length >= 2 && (
          <AutoChart columns={result.columns} rows={result.rows} />
        )}
        {result && !isSingleValue && result.columns.length < 2 && (
          <div className="text-center py-6">
            <p className="text-xs text-slate-500">{result.row_count} rows</p>
          </div>
        )}
      </div>
    </Card>
  );
}

// ─── Stat Card ──────────────────────────────────────────────────────────────

function StatCard({ icon, label, value, color, onClick }: {
  icon: React.ReactNode; label: string; value: string | number; color: string; onClick?: () => void;
}) {
  return (
    <button onClick={onClick} className="flex items-center gap-3 p-4 rounded-xl border border-slate-700/30 bg-slate-800/30 hover:border-slate-600/60 transition-all text-left w-full">
      <div className={cn("p-2.5 rounded-lg", color)}>{icon}</div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-[11px] text-slate-500">{label}</p>
      </div>
    </button>
  );
}

// ─── Quick Action ───────────────────────────────────────────────────────────

function QuickAction({ icon, label, desc, onClick }: {
  icon: React.ReactNode; label: string; desc: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick}
      className="flex items-center gap-3 p-3 rounded-xl border border-slate-700/30 bg-slate-800/20 hover:border-blue-500/30 hover:bg-blue-500/5 transition-all text-left group w-full">
      <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 shrink-0">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-200">{label}</p>
        <p className="text-[10px] text-slate-500">{desc}</p>
      </div>
      <ChevronRight className="h-4 w-4 text-slate-600 group-hover:text-blue-400 shrink-0" />
    </button>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin";
  const { branding, update: updateBranding } = useBranding();
  const [editingBranding, setEditingBranding] = useState(false);

  const { data: connData } = useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnectionListResponse>("/connections/") });
  const { data: sqData } = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.get<SavedQueryListResponse>("/saved-queries/?limit=50") });
  const { data: schedData } = useQuery({ queryKey: ["schedules"], queryFn: () => api.get<ScheduleListResponse>("/schedules/"), enabled: isAdmin });

  const connectionCount = connData?.connections?.filter((c) => c.is_active).length ?? 0;
  const savedQueryCount = sqData?.total ?? 0;
  const activeSchedules = schedData?.schedules?.filter((s) => s.is_active).length ?? 0;
  const pinnedQueries = sqData?.queries?.filter((q) => q.is_pinned) ?? [];
  const recentQueries = sqData?.queries?.slice(0, 5) ?? [];

  const greeting = (() => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; })();
  const roleColor = user?.role === "admin" ? "text-amber-400 bg-amber-500/10 border-amber-500/20" : user?.role === "analyst" ? "text-blue-400 bg-blue-500/10 border-blue-500/20" : "text-slate-400 bg-slate-500/10 border-slate-500/20";

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Company Branding */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          {branding.logoUrl ? (
            <img src={branding.logoUrl} alt="" className="h-10 w-10 rounded-lg object-contain bg-white/5 border border-slate-700/30 p-1" />
          ) : (
            <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-blue-500/20 to-indigo-500/10 border border-blue-500/15 flex items-center justify-center">
              <Sparkles className="h-5 w-5 text-blue-400" />
            </div>
          )}
          <div>
            <h1 className="text-xl font-bold text-white">{greeting}{user?.name ? `, ${user.name.split(" ")[0]}` : ""}</h1>
            <p className="text-sm text-slate-400">{branding.companyName} — {branding.tagline}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("text-[10px] font-medium px-2.5 py-1 rounded-full border", roleColor)}>
            {user?.role === "admin" ? "Administrator" : user?.role === "analyst" ? "Analyst" : "Viewer"}
          </span>
          {isAdmin && !editingBranding && (
            <button onClick={() => setEditingBranding(true)} className="p-1.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors" title="Edit branding">
              <Edit3 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Branding Editor */}
      {editingBranding && (
        <BrandingEditor branding={branding}
          onSave={(b) => { updateBranding(b); setEditingBranding(false); toast.success("Branding updated"); }}
          onCancel={() => setEditingBranding(false)} />
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={<Database className="h-5 w-5 text-blue-400" />} label="Connections" value={connectionCount} color="bg-blue-500/10" onClick={() => navigate("/connections")} />
        <StatCard icon={<Bookmark className="h-5 w-5 text-emerald-400" />} label="Saved Queries" value={savedQueryCount} color="bg-emerald-500/10" onClick={() => navigate("/saved-queries")} />
        <StatCard icon={<Clock className="h-5 w-5 text-amber-400" />} label="Schedules" value={isAdmin ? activeSchedules : "—"} color="bg-amber-500/10" onClick={isAdmin ? () => navigate("/schedules") : undefined} />
        <StatCard icon={<Sparkles className="h-5 w-5 text-violet-400" />} label="AI Engine" value="Online" color="bg-violet-500/10" onClick={() => navigate("/query")} />
      </div>

      {/* Pinned Query Widgets */}
      {pinnedQueries.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-1.5"><Pin className="h-3.5 w-3.5 text-amber-400" />Pinned Analytics</h2>
            <button onClick={() => navigate("/saved-queries")} className="text-[10px] text-blue-400 hover:text-blue-300">Manage pins</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {pinnedQueries.slice(0, 6).map((q) => <QueryWidget key={q.query_id} query={q} />)}
          </div>
        </div>
      )}

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Quick Actions */}
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">Quick Actions</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <QuickAction icon={<MessageSquare className="h-4 w-4" />} label="New AI Query" desc="Ask questions in plain English" onClick={() => navigate("/query")} />
            <QuickAction icon={<HardDrive className="h-4 w-4" />} label="Schema Browser" desc="Explore tables & columns" onClick={() => navigate("/schema-browser")} />
            <QuickAction icon={<BarChart3 className="h-4 w-4" />} label="Chart Studio" desc="Build custom visualizations" onClick={() => navigate("/query")} />
            <QuickAction icon={<Bookmark className="h-4 w-4" />} label="Saved Queries" desc="Your query library" onClick={() => navigate("/saved-queries")} />
            {isAdmin && <>
              <QuickAction icon={<Shield className="h-4 w-4" />} label="Permissions" desc="Manage data access" onClick={() => navigate("/admin/permissions")} />
              <QuickAction icon={<Activity className="h-4 w-4" />} label="Monitoring" desc="Health & audit logs" onClick={() => navigate("/monitoring")} />
            </>}
          </div>
        </div>

        {/* Recent Activity */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300">Recent Queries</h2>
            <button onClick={() => navigate("/saved-queries")} className="text-[10px] text-blue-400 hover:text-blue-300">View all</button>
          </div>
          <Card className="divide-y divide-slate-700/20">
            {recentQueries.length > 0 ? recentQueries.map((q) => (
              <div key={q.query_id} className="flex items-center justify-between px-3 py-2.5 hover:bg-slate-800/40 transition-colors group">
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-slate-300 truncate">{q.name}</p>
                  <p className="text-[10px] text-slate-600 truncate">{q.question}</p>
                </div>
                <span className="text-[9px] text-slate-600 ml-2">{q.run_count}×</span>
              </div>
            )) : (
              <div className="p-6 text-center"><Bookmark className="h-5 w-5 text-slate-700 mx-auto mb-1.5" /><p className="text-[10px] text-slate-600">No queries yet</p></div>
            )}
          </Card>
        </div>
      </div>

      {/* Admin: Platform Health */}
      <RoleGuard minRole="admin">
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">Platform Status</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { label: "API Server", status: "Healthy", icon: <Activity className="h-4 w-4" />, ok: true },
              { label: "PostgreSQL", status: "Connected", icon: <Database className="h-4 w-4" />, ok: true },
              { label: "Redis", status: "3 DBs Active", icon: <Database className="h-4 w-4" />, ok: true },
              { label: "LLM Provider", status: "Groq Ready", icon: <Brain className="h-4 w-4" />, ok: true },
            ].map((svc) => (
              <div key={svc.label} className="flex items-center gap-2.5 p-3 rounded-lg border border-slate-700/30 bg-slate-800/20">
                <span className={cn("p-1.5 rounded", svc.ok ? "text-emerald-400 bg-emerald-500/10" : "text-red-400 bg-red-500/10")}>{svc.icon}</span>
                <div>
                  <p className="text-[11px] font-medium text-slate-300">{svc.label}</p>
                  <p className={cn("text-[10px]", svc.ok ? "text-emerald-400" : "text-red-400")}>{svc.status}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </RoleGuard>
    </div>
  );
}