/**
 * Smart BI Agent — Dashboard v3 (Command Center)
 * Session 12 | Animated, branded, world-class
 *
 * Features:
 *   - Company branding (admin editable)
 *   - Animated count-up stat cards
 *   - Pinned query widgets (live KPIs)
 *   - Quick actions with hover effects
 *   - Platform health (admin)
 *   - Staggered entry animations
 *   - Keyboard shortcut: Ctrl+Q → AI Query
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  MessageSquare, Database, Bookmark, Clock, Shield,
  BarChart3, HardDrive, Activity, ChevronRight,
  Sparkles, Play, Brain, Edit3, Check, X,
  Loader2, Pin, Palette,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { Card, Input } from "@/components/ui";
import { RoleGuard } from "@/components/auth";
import { AutoChart, Scorecard } from "@/components/QueryResults";
import { useAnimateIn, useCountUp, stagger, useKeyboardShortcuts, injectAnimations } from "@/lib/animations";
import type { ConnectionListResponse } from "@/types/connections";
import type { SavedQueryListResponse, SavedQuery } from "@/types/saved-queries";
import type { ScheduleListResponse } from "@/types/schedules";
import type { QueryRequest, QueryResponse } from "@/types/query";

// ─── Branding ───────────────────────────────────────────────────────────────

const DEFAULT_BRANDING = { companyName: "Smart BI Agent", logoUrl: "", tagline: "AI-Powered Business Intelligence" };

type BrandingType = typeof DEFAULT_BRANDING;

function useBranding() {
  const [branding, setBranding] = useState(DEFAULT_BRANDING);
  const [loaded, setLoaded] = useState(false);

  // Load from API on mount, fall back to sessionStorage
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ branding: { company_name: string; logo_url: string; tagline: string } }>("/settings/branding");
        if (!cancelled && res.branding) {
          const b: BrandingType = {
            companyName: res.branding.company_name,
            logoUrl: res.branding.logo_url,
            tagline: res.branding.tagline,
          };
          setBranding(b);
        }
      } catch {
        // API not available yet — try sessionStorage fallback
        try { const s = sessionStorage.getItem("sbi_branding"); if (s) setBranding(JSON.parse(s)); } catch {}
      }
      if (!cancelled) setLoaded(true);
    })();
    return () => { cancelled = true; };
  }, []);

  const update = async (b: BrandingType) => {
    setBranding(b);
    // Persist to both API and sessionStorage (fallback)
    try { sessionStorage.setItem("sbi_branding", JSON.stringify(b)); } catch {}
    try {
      await api.put("/settings/branding", {
        company_name: b.companyName,
        logo_url: b.logoUrl,
        tagline: b.tagline,
      });
    } catch {}
  };

  return { branding, update, loaded };
}

// ─── Animated Stat Card ─────────────────────────────────────────────────────

function StatCard({ icon, label, value, color, onClick, delay = 0 }: {
  icon: React.ReactNode; label: string; value: number | string; color: string; onClick?: () => void; delay?: number;
}) {
  const numValue = typeof value === "number" ? value : 0;
  const displayNum = useCountUp(numValue, 1200);
  const anim = useAnimateIn("fade-up", delay);

  return (
    <button onClick={onClick} className={cn(
      "flex items-center gap-3 p-4 rounded-xl border border-slate-700/30 bg-slate-800/20 transition-all text-left w-full group",
      "hover:border-slate-600/50 hover:bg-slate-800/40 hover:shadow-lg hover:shadow-blue-500/5 hover:-translate-y-0.5",
      anim,
    )}>
      <div className={cn("p-2.5 rounded-xl transition-transform group-hover:scale-110", color)}>{icon}</div>
      <div>
        <p className="text-2xl font-bold text-white tabular-nums">
          {typeof value === "number" ? displayNum.toLocaleString() : value}
        </p>
        <p className="text-[11px] text-slate-500">{label}</p>
      </div>
    </button>
  );
}

// ─── Quick Action ───────────────────────────────────────────────────────────

function QuickAction({ icon, label, desc, onClick, delay = 0 }: {
  icon: React.ReactNode; label: string; desc: string; onClick: () => void; delay?: number;
}) {
  const anim = useAnimateIn("fade-up", delay);
  return (
    <button onClick={onClick} className={cn(
      "flex items-center gap-3 p-3.5 rounded-xl border border-slate-700/30 bg-slate-800/15 transition-all text-left group w-full",
      "hover:border-blue-500/25 hover:bg-blue-500/5 hover:shadow-md hover:shadow-blue-500/5",
      anim,
    )}>
      <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 group-hover:bg-blue-500/15 group-hover:scale-110 transition-all shrink-0">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-200 group-hover:text-white transition-colors">{label}</p>
        <p className="text-[10px] text-slate-500">{desc}</p>
      </div>
      <ChevronRight className="h-4 w-4 text-slate-700 group-hover:text-blue-400 group-hover:translate-x-0.5 transition-all shrink-0" />
    </button>
  );
}

// ─── Live Query Widget ──────────────────────────────────────────────────────

function StudioDashboards() {
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["dashboards-home"],
    queryFn: () => api.get<{ dashboards: Array<{ dashboard_id: string; name: string; description: string; config: any; updated_at: string }> }>("/dashboards/"),
  });

  const dashboards = data?.dashboards ?? [];
  if (dashboards.length === 0) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-1.5"><Palette className="h-3.5 w-3.5 text-violet-400" />Your Dashboards</h2>
        <button onClick={() => navigate("/studio")} className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors">Open Studio</button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {dashboards.slice(0, 4).map((d) => {
          const widgetCount = d.config?.widgets?.length ?? 0;
          const updated = new Date(d.updated_at).toLocaleDateString("en-US", { month: "short", day: "numeric" });
          return (
            <button key={d.dashboard_id} onClick={() => navigate("/studio")}
              className="flex items-center gap-3 p-3 rounded-xl border border-slate-700/25 bg-slate-800/15 hover:border-violet-500/25 hover:bg-violet-500/5 transition-all duration-200 text-left group">
              <div className="p-2 rounded-lg bg-violet-500/10 text-violet-400 group-hover:bg-violet-500/15 transition-all shrink-0">
                <Palette className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-slate-200 truncate group-hover:text-white transition-colors">{d.name}</p>
                <p className="text-[10px] text-slate-600">{widgetCount} visual{widgetCount !== 1 ? "s" : ""} · {updated}</p>
              </div>
              <ChevronRight className="h-3 w-3 text-slate-700 group-hover:text-violet-400 transition-colors shrink-0" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─── Live Query Widget ──────────────────────────────────────────────────────

function QueryWidget({ query }: { query: SavedQuery }) {
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await api.post<QueryResponse>("/query/", { question: query.question, connection_id: query.connection_id } as QueryRequest);
        setResult(res);
      } catch {} finally { setLoading(false); }
    })();
  }, [query.query_id]);

  const isKpi = result && result.rows.length === 1 && result.columns.length <= 3;

  return (
    <Card className="overflow-hidden hover:border-slate-600/50 transition-all hover:shadow-lg hover:shadow-blue-500/3">
      <div className="px-3 py-2 border-b border-slate-700/30 flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-300 truncate">{query.name}</p>
          <p className="text-[9px] text-slate-600 truncate">{query.question}</p>
        </div>
        {loading && <Loader2 className="h-3 w-3 text-blue-400 animate-spin shrink-0" />}
      </div>
      <div style={{ minHeight: 120 }}>
        {loading && !result && (
          <div className="flex items-center justify-center h-28">
            <div className="w-full h-full sbi-shimmer rounded" />
          </div>
        )}
        {result && isKpi && <Scorecard columns={result.columns} rows={result.rows} />}
        {result && !isKpi && result.columns.length >= 2 && (
          <div className="p-2"><AutoChart columns={result.columns} rows={result.rows} /></div>
        )}
      </div>
    </Card>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin";
  const { branding, update: updateBranding } = useBranding();
  const [editBranding, setEditBranding] = useState(false);
  const [bName, setBName] = useState(branding.companyName);
  const [bLogo, setBLogo] = useState(branding.logoUrl);
  const [bTag, setBTag] = useState(branding.tagline);
  const heroAnim = useAnimateIn("fade-up", 0);

  useEffect(() => { injectAnimations(); }, []);

  // Keyboard shortcuts
  useKeyboardShortcuts({
    "ctrl+q": () => navigate("/query"),
    "ctrl+shift+s": () => navigate("/studio"),
    "ctrl+shift+b": () => navigate("/schema-browser"),
  });

  const { data: connData } = useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnectionListResponse>("/connections/") });
  const { data: sqData } = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.get<SavedQueryListResponse>("/saved-queries/?limit=50") });
  const { data: schedData } = useQuery({ queryKey: ["schedules"], queryFn: () => api.get<ScheduleListResponse>("/schedules/"), enabled: isAdmin });

  const connCount = connData?.connections?.filter((c) => c.is_active).length ?? 0;
  const sqCount = sqData?.total ?? 0;
  const schedCount = schedData?.schedules?.filter((s) => s.is_active).length ?? 0;
  const pinnedQueries = sqData?.queries?.filter((q) => q.is_pinned) ?? [];
  const recentQueries = sqData?.queries?.slice(0, 5) ?? [];

  const greeting = (() => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; })();
  const roleColor = user?.role === "admin" ? "text-amber-400 bg-amber-500/10 border-amber-500/20" : user?.role === "analyst" ? "text-blue-400 bg-blue-500/10 border-blue-500/20" : "text-slate-400 bg-slate-500/10 border-slate-500/20";

  return (
    <div className="space-y-7 max-w-6xl pb-8">
      {/* ── Hero / Branding ── */}
      <div className={heroAnim}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {branding.logoUrl ? (
              <img src={branding.logoUrl} alt="" className="h-12 w-12 rounded-xl object-contain bg-white/5 border border-slate-700/30 p-1.5" />
            ) : (
              <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-blue-500/20 to-violet-500/15 border border-blue-500/10 flex items-center justify-center sbi-pulse-glow">
                <Sparkles className="h-6 w-6 text-blue-400" />
              </div>
            )}
            <div>
              <h1 className="text-2xl font-bold text-white">{greeting}{user?.name ? `, ${user.name.split(" ")[0]}` : ""}</h1>
              <p className="text-sm text-slate-400">{branding.companyName} · {branding.tagline}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("text-[10px] font-medium px-2.5 py-1 rounded-full border", roleColor)}>
              {user?.role === "admin" ? "Administrator" : user?.role === "analyst" ? "Analyst" : "Viewer"}
            </span>
            {isAdmin && !editBranding && (
              <button onClick={() => { setBName(branding.companyName); setBLogo(branding.logoUrl); setBTag(branding.tagline); setEditBranding(true); }}
                className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-all"><Edit3 className="h-3.5 w-3.5" /></button>
            )}
          </div>
        </div>
        {editBranding && (
          <div className="flex items-center gap-2 mt-3 p-3 rounded-xl border border-blue-500/20 bg-blue-500/5">
            <Input placeholder="Company Name" value={bName} onChange={(e) => setBName(e.target.value)} className="h-8 text-sm flex-1" />
            <Input placeholder="Logo URL" value={bLogo} onChange={(e) => setBLogo(e.target.value)} className="h-8 text-sm flex-1" />
            <Input placeholder="Tagline" value={bTag} onChange={(e) => setBTag(e.target.value)} className="h-8 text-sm flex-1" />
            <button onClick={() => { updateBranding({ companyName: bName, logoUrl: bLogo, tagline: bTag }); setEditBranding(false); toast.success("Branding updated"); }}
              className="p-1.5 rounded text-emerald-400 hover:bg-emerald-500/10"><Check className="h-4 w-4" /></button>
            <button onClick={() => setEditBranding(false)} className="p-1.5 rounded text-slate-400 hover:bg-slate-700/50"><X className="h-4 w-4" /></button>
          </div>
        )}
      </div>

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={<Database className="h-5 w-5 text-blue-400" />} label="Connections" value={connCount} color="bg-blue-500/10" onClick={() => navigate("/connections")} delay={100} />
        <StatCard icon={<Bookmark className="h-5 w-5 text-emerald-400" />} label="Saved Queries" value={sqCount} color="bg-emerald-500/10" onClick={() => navigate("/saved-queries")} delay={150} />
        <StatCard icon={<Clock className="h-5 w-5 text-amber-400" />} label="Schedules" value={isAdmin ? schedCount : 0} color="bg-amber-500/10" onClick={isAdmin ? () => navigate("/schedules") : undefined} delay={200} />
        <StatCard icon={<Sparkles className="h-5 w-5 text-violet-400" />} label="AI Engine" value="Online" color="bg-violet-500/10" onClick={() => navigate("/query")} delay={250} />
      </div>

      {/* ── Pinned Widgets ── */}
      {pinnedQueries.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-1.5"><Pin className="h-3.5 w-3.5 text-amber-400" />Pinned Analytics</h2>
            <button onClick={() => navigate("/saved-queries")} className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors">Manage pins</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {pinnedQueries.slice(0, 6).map((q, i) => (
              <div key={q.query_id} style={{ transitionDelay: stagger(i, 80) }} className="transition-all duration-500 opacity-100">
                <QueryWidget query={q} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Quick Actions + Studio Dashboards + Recent ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-300">Quick Actions</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <QuickAction icon={<MessageSquare className="h-4 w-4" />} label="AI Query" desc="Ask in plain English · Ctrl+Q" onClick={() => navigate("/query")} delay={300} />
              <QuickAction icon={<Palette className="h-4 w-4" />} label="Dashboard Studio" desc="Build Power BI-style dashboards" onClick={() => navigate("/studio")} delay={350} />
              <QuickAction icon={<HardDrive className="h-4 w-4" />} label="Schema Browser" desc="Explore tables & columns" onClick={() => navigate("/schema-browser")} delay={400} />
              <QuickAction icon={<Bookmark className="h-4 w-4" />} label="Saved Queries" desc="Your query library" onClick={() => navigate("/saved-queries")} delay={450} />
              {isAdmin && <>
                <QuickAction icon={<Shield className="h-4 w-4" />} label="Permissions" desc="Manage data access" onClick={() => navigate("/admin/permissions")} delay={500} />
                <QuickAction icon={<Activity className="h-4 w-4" />} label="Monitoring" desc="Health & audit logs" onClick={() => navigate("/monitoring")} delay={550} />
              </>}
            </div>
          </div>

          {/* Studio Dashboards */}
          <StudioDashboards />
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300">Recent Queries</h2>
            <button onClick={() => navigate("/saved-queries")} className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors">View all</button>
          </div>
          <Card className="divide-y divide-slate-700/20 overflow-hidden">
            {recentQueries.length > 0 ? recentQueries.map((q, i) => (
              <button key={q.query_id} onClick={() => navigate("/query")}
                className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-blue-500/5 transition-all text-left group"
                style={{ transitionDelay: stagger(i, 40) }}>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-slate-300 truncate group-hover:text-white transition-colors">{q.name}</p>
                  <p className="text-[10px] text-slate-600 truncate">{q.question}</p>
                </div>
                <Play className="h-3 w-3 text-slate-700 group-hover:text-blue-400 transition-colors shrink-0 ml-2" />
              </button>
            )) : (
              <div className="p-8 text-center"><Bookmark className="h-5 w-5 text-slate-700 mx-auto mb-2" /><p className="text-[10px] text-slate-600">No queries yet</p></div>
            )}
          </Card>
        </div>
      </div>

      {/* ── Platform Health (admin) ── */}
      <RoleGuard minRole="admin">
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">Platform Status</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { label: "API Server", status: "Healthy", icon: <Activity className="h-4 w-4" /> },
              { label: "PostgreSQL", status: "Connected", icon: <Database className="h-4 w-4" /> },
              { label: "Redis", status: "3 DBs Active", icon: <Database className="h-4 w-4" /> },
              { label: "LLM Provider", status: "Ready", icon: <Brain className="h-4 w-4" /> },
            ].map((svc, i) => (
              <div key={svc.label} className={cn("flex items-center gap-2.5 p-3 rounded-xl border border-slate-700/20 bg-slate-800/15 transition-all duration-500",
                useAnimateIn("fade-up", 600 + i * 60))}>
                <span className="p-1.5 rounded-lg text-emerald-400 bg-emerald-500/10">{svc.icon}</span>
                <div><p className="text-[11px] font-medium text-slate-300">{svc.label}</p><p className="text-[10px] text-emerald-400">{svc.status}</p></div>
              </div>
            ))}
          </div>
        </div>
      </RoleGuard>

      {/* Footer hint */}
      <p className="text-center text-[9px] text-slate-700 pt-4">
        Keyboard shortcuts: Ctrl+Q AI Query · Ctrl+Shift+S Studio · Ctrl+Shift+B Schema Browser
      </p>
    </div>
  );
}
