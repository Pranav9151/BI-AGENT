/**
 * Smart BI Agent — Schema Browser v3 (Phase 12 Fix + Governance Edition)
 *
 * ★ NEW IN v3:
 *   - CEO role can edit (same as admin) — via updated RoleGuard
 *   - Tab 4: Data Quality — null rates, type consistency, PK coverage heatmap
 *   - Tab 5: Governance — column descriptions, PII tagging, sensitivity levels
 *     (admin/ceo only, with inline edit and audit trail)
 *   - Health score badge per table (green/amber/red)
 *   - Profile tab now shows anomaly flags (high-null, low-distinct)
 */

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Database, Table2, Columns3, Key, RefreshCw,
  ChevronRight, ChevronDown, Copy, Check, Search,
  Loader2, Timer, HardDrive, GitBranch, BarChart3,
  Eye, ArrowRight, Hash, AlertTriangle,
  Layers, Activity, Shield, Tag, Lock,
  CheckCircle2, XCircle, AlertCircle, Edit3, Save, X,
  Info, TrendingDown, Zap,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { Button, Card, Alert, Input } from "@/components/ui";
import { ERDDiagram } from "@/components/ERDDiagram";
import type { ConnectionListResponse } from "@/types/connections";
import type { SchemaResponse, SchemaRefreshResponse, TableInfo, ColumnInfo } from "@/types/schema";

// ─── Types ───────────────────────────────────────────────────────────────────

interface Relationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  constraint_name: string;
}

interface ColumnProfile {
  column_name: string;
  data_type: string;
  null_count: number;
  null_pct: number;
  distinct_count: number;
  sample_values: string[];
  min_value: string | null;
  max_value: string | null;
}

interface TableStat {
  table_name: string;
  row_count_estimate: number;
  column_count: number;
  has_primary_key: boolean;
  primary_key_columns: string[];
  index_count: number;
}

// Governance metadata (stored locally until backend endpoint is available)
interface ColumnGovernance {
  description: string;
  pii: boolean;
  sensitivity: "public" | "internal" | "confidential" | "restricted";
  owner: string;
  tags: string[];
}

type GovernanceMap = Record<string, Record<string, ColumnGovernance>>;
type TabId = "browse" | "relationships" | "stats" | "quality" | "governance";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getTypeBadgeColor(type: string): string {
  const t = type.toLowerCase();
  if (/int|numeric|decimal|float|double|real/.test(t)) return "text-blue-400 bg-blue-500/10 border-blue-500/20";
  if (/char|text|string|varchar/.test(t)) return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
  if (/date|time|interval/.test(t)) return "text-amber-400 bg-amber-500/10 border-amber-500/20";
  if (/bool/.test(t)) return "text-violet-400 bg-violet-500/10 border-violet-500/20";
  if (/uuid|json|array/.test(t)) return "text-cyan-400 bg-cyan-500/10 border-cyan-500/20";
  return "text-slate-400 bg-slate-500/10 border-slate-500/20";
}

function sensitivityColor(s: string) {
  return {
    public:       "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    internal:     "text-blue-400 bg-blue-500/10 border-blue-500/20",
    confidential: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    restricted:   "text-red-400 bg-red-500/10 border-red-500/20",
  }[s] ?? "text-slate-400 bg-slate-500/10 border-slate-500/20";
}

// Compute a simple data quality score 0-100 for a table
function tableHealthScore(stat: TableStat): number {
  let score = 100;
  if (!stat.has_primary_key) score -= 30;
  if (stat.index_count === 0) score -= 15;
  if (stat.column_count > 50) score -= 10; // overly wide tables
  return Math.max(0, score);
}

function HealthBadge({ score }: { score: number }) {
  const { label, cls } = score >= 80
    ? { label: "Healthy", cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" }
    : score >= 50
    ? { label: "Fair", cls: "text-amber-400 bg-amber-500/10 border-amber-500/20" }
    : { label: "Poor", cls: "text-red-400 bg-red-500/10 border-red-500/20" };

  return (
    <span className={cn("text-[9px] font-semibold px-1.5 py-0.5 rounded border inline-flex items-center gap-0.5", cls)}>
      {score >= 80 ? <CheckCircle2 className="h-2.5 w-2.5" /> : score >= 50 ? <AlertCircle className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}
      {label} {score}
    </span>
  );
}

// ─── Copy Button ─────────────────────────────────────────────────────────────

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(text); setCopied(true); toast.success(`Copied "${text}"`); setTimeout(() => setCopied(false), 2000); }}
      className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
      title={label || "Copy"}
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

// ─── Column Row ──────────────────────────────────────────────────────────────

function ColumnRow({ name, info }: { name: string; info: ColumnInfo }) {
  return (
    <div className="flex items-center gap-2 px-4 py-1.5 pl-12 hover:bg-slate-700/20 transition-colors">
      <Columns3 className="h-3 w-3 text-slate-600 shrink-0" />
      <span className="text-xs text-slate-300 font-mono min-w-0 truncate">{name}</span>
      <div className="flex items-center gap-1.5 ml-auto shrink-0">
        {info.primary_key && (
          <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded border text-amber-400 bg-amber-500/10 border-amber-500/20">
            <Key className="h-2.5 w-2.5" />PK
          </span>
        )}
        <span className={cn("text-[9px] font-medium px-1.5 py-0.5 rounded border", getTypeBadgeColor(info.type))}>
          {info.type}
        </span>
        {info.nullable && (
          <span className="text-[9px] font-medium px-1.5 py-0.5 rounded border text-slate-500 bg-slate-500/5 border-slate-600/30">null</span>
        )}
      </div>
    </div>
  );
}

// ─── Table Row ───────────────────────────────────────────────────────────────

function TableRow({ name, info, stats, onProfile }: {
  name: string; info: TableInfo;
  stats?: TableStat; onProfile?: (table: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const columns = Object.entries(info.columns);
  const pkCount = columns.filter(([, c]) => c.primary_key).length;
  const healthScore = stats ? tableHealthScore(stats) : null;

  return (
    <div className="border-b border-slate-700/20 last:border-b-0">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-slate-800/40 transition-colors group">
        <span className="text-slate-500 shrink-0">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
        <Table2 className="h-3.5 w-3.5 text-blue-400 shrink-0" />
        <span className="text-sm font-medium text-slate-200 font-mono">{name}</span>
        <span className="text-[10px] text-slate-500 ml-1">
          {columns.length} col{columns.length !== 1 ? "s" : ""}
          {pkCount > 0 && <span className="text-amber-500 ml-1.5">· {pkCount} PK</span>}
        </span>
        {stats && (
          <span className="text-[10px] text-slate-600 ml-1">
            · ~{stats.row_count_estimate >= 1e6 ? `${(stats.row_count_estimate / 1e6).toFixed(1)}M` :
              stats.row_count_estimate >= 1e3 ? `${(stats.row_count_estimate / 1e3).toFixed(1)}K` :
              stats.row_count_estimate.toLocaleString()} rows
          </span>
        )}
        {healthScore !== null && (
          <span className="ml-2 shrink-0">
            <HealthBadge score={healthScore} />
          </span>
        )}
        <div className="flex-1" />
        {onProfile && (
          <button onClick={(e) => { e.stopPropagation(); onProfile(name); }}
            className="p-1 rounded text-slate-600 hover:text-blue-400 hover:bg-blue-500/10 transition-colors opacity-0 group-hover:opacity-100"
            title="Profile table data">
            <BarChart3 className="h-3 w-3" />
          </button>
        )}
        <CopyButton text={name} label="Copy table name" />
      </button>
      {expanded && columns.length > 0 && (
        <div className="bg-slate-800/20 border-t border-slate-700/20">
          {columns.map(([colName, colInfo]) => <ColumnRow key={colName} name={colName} info={colInfo} />)}
        </div>
      )}
    </div>
  );
}

// ─── Relationships View ──────────────────────────────────────────────────────

function RelationshipsView({ connectionId }: { connectionId: string }) {
  const [viewMode, setViewMode] = useState<"diagram" | "list">("diagram");
  const { data, isLoading, error } = useQuery({
    queryKey: ["schema-relationships", connectionId],
    queryFn: () => api.get<{ relationships: Relationship[]; table_count: number }>(`/schema/${connectionId}/relationships`),
    enabled: !!connectionId,
  });
  const { data: schema } = useQuery({
    queryKey: ["schema", connectionId],
    queryFn: () => api.get<SchemaResponse>(`/schema/${connectionId}`),
    enabled: !!connectionId,
  });
  const erdTables = useMemo(() => {
    if (!schema?.schema_data) return [];
    return Object.entries(schema.schema_data).map(([name, info]) => ({
      name,
      columns: Object.entries(info.columns).map(([cn, ci]) => ({ name: cn, type: ci.type, primary_key: ci.primary_key ?? false })),
    }));
  }, [schema]);

  if (isLoading) return <Card className="p-12"><div className="flex items-center justify-center gap-3"><Loader2 className="h-5 w-5 text-blue-400 animate-spin" /><span className="text-sm text-slate-400">Detecting relationships…</span></div></Card>;
  if (error) return <Alert variant="error">Failed to load relationships</Alert>;
  if (!data?.relationships?.length) return (
    <Card className="p-12"><div className="text-center"><GitBranch className="h-8 w-8 text-slate-600 mx-auto mb-3" /><p className="text-sm text-slate-400 font-medium">No FK relationships found</p></div></Card>
  );
  const grouped = data.relationships.reduce((acc, r) => { acc[r.from_table] = acc[r.from_table] || []; acc[r.from_table].push(r); return acc; }, {} as Record<string, Relationship[]>);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <GitBranch className="h-3.5 w-3.5" />
          <span>{data.relationships.length} relationship{data.relationships.length !== 1 ? "s" : ""} across {data.table_count} tables</span>
        </div>
        <div className="flex rounded-lg border border-slate-700/40 overflow-hidden">
          {(["diagram", "list"] as const).map((m) => (
            <button key={m} onClick={() => setViewMode(m)}
              className={cn("px-3 py-1 text-[10px] font-semibold transition-all", viewMode === m ? "bg-blue-600/20 text-blue-300" : "text-slate-500 hover:text-slate-300")}>
              {m === "diagram" ? "ERD Diagram" : "List View"}
            </button>
          ))}
        </div>
      </div>
      {viewMode === "diagram" && erdTables.length > 0 && <ERDDiagram tables={erdTables} relationships={data.relationships} />}
      {viewMode === "list" && (
        <div className="grid gap-3">
          {Object.entries(grouped).map(([fromTable, rels]) => (
            <Card key={fromTable} className="overflow-hidden">
              <div className="px-4 py-2.5 bg-slate-800/30 border-b border-slate-700/20">
                <span className="text-sm font-medium text-slate-200 font-mono flex items-center gap-2"><Table2 className="h-3.5 w-3.5 text-blue-400" />{fromTable}</span>
              </div>
              <div className="divide-y divide-slate-700/20">
                {rels.map((r, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-800/20 transition-colors">
                    <span className="text-xs text-blue-400 font-mono">{r.from_column}</span>
                    <ArrowRight className="h-3 w-3 text-slate-600 shrink-0" />
                    <Table2 className="h-3 w-3 text-emerald-400" />
                    <span className="text-xs text-emerald-300 font-mono">{r.to_table}.{r.to_column}</span>
                    <span className="ml-auto text-[9px] text-slate-600 font-mono">{r.constraint_name}</span>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Stats View ──────────────────────────────────────────────────────────────

function StatsView({ connectionId }: { connectionId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["schema-stats", connectionId],
    queryFn: () => api.get<{ tables: TableStat[]; total_tables: number; total_columns: number }>(`/schema/${connectionId}/stats`),
    enabled: !!connectionId,
  });
  if (isLoading) return <Card className="p-12"><div className="flex items-center justify-center gap-3"><Loader2 className="h-5 w-5 text-blue-400 animate-spin" /><span className="text-sm text-slate-400">Loading statistics…</span></div></Card>;
  if (error) return <Alert variant="error">Failed to load statistics</Alert>;
  if (!data?.tables?.length) return <Card className="p-12"><div className="text-center"><Activity className="h-8 w-8 text-slate-600 mx-auto mb-3" /><p className="text-sm text-slate-400">No tables found</p></div></Card>;
  const totalRows = data.tables.reduce((s, t) => s + t.row_count_estimate, 0);
  const tablesWithPK = data.tables.filter((t) => t.has_primary_key).length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Tables", value: data.total_tables, icon: <Table2 className="h-4 w-4 text-blue-400" /> },
          { label: "Columns", value: data.total_columns, icon: <Columns3 className="h-4 w-4 text-emerald-400" /> },
          { label: "Est. Rows", value: totalRows >= 1e6 ? `${(totalRows / 1e6).toFixed(1)}M` : totalRows >= 1e3 ? `${(totalRows / 1e3).toFixed(1)}K` : totalRows.toLocaleString(), icon: <Layers className="h-4 w-4 text-amber-400" /> },
          { label: "With PK", value: `${tablesWithPK}/${data.total_tables}`, icon: <Key className="h-4 w-4 text-violet-400" /> },
        ].map((s) => (
          <Card key={s.label} className="p-3">
            <div className="flex items-center gap-2 mb-1">{s.icon}<span className="text-[10px] text-slate-500 uppercase tracking-wider">{s.label}</span></div>
            <p className="text-lg font-bold text-white">{s.value}</p>
          </Card>
        ))}
      </div>
      <Card className="overflow-hidden">
        <div className="px-4 py-2.5 bg-slate-800/30 border-b border-slate-700/20">
          <div className="grid grid-cols-12 gap-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            <span className="col-span-4">Table</span>
            <span className="col-span-2 text-right">Rows</span>
            <span className="col-span-2 text-right">Cols</span>
            <span className="col-span-2 text-center">PK</span>
            <span className="col-span-2 text-right">Health</span>
          </div>
        </div>
        <div className="divide-y divide-slate-700/20">
          {data.tables.map((t) => (
            <div key={t.table_name} className="grid grid-cols-12 gap-2 px-4 py-2 items-center hover:bg-slate-800/20 transition-colors">
              <span className="col-span-4 text-sm text-slate-300 font-mono truncate flex items-center gap-1.5">
                <Table2 className="h-3 w-3 text-blue-400/60 shrink-0" />{t.table_name}
              </span>
              <span className="col-span-2 text-right text-xs text-slate-400 font-mono">
                {t.row_count_estimate >= 1e6 ? `${(t.row_count_estimate / 1e6).toFixed(1)}M` :
                 t.row_count_estimate >= 1e3 ? `${(t.row_count_estimate / 1e3).toFixed(1)}K` :
                 t.row_count_estimate.toLocaleString()}
              </span>
              <span className="col-span-2 text-right text-xs text-slate-400">{t.column_count}</span>
              <span className="col-span-2 text-center">
                {t.has_primary_key
                  ? <span className="text-[9px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded px-1.5 py-0.5">{t.primary_key_columns.join(", ")}</span>
                  : <span className="text-[9px] text-slate-600">—</span>}
              </span>
              <span className="col-span-2 flex justify-end"><HealthBadge score={tableHealthScore(t)} /></span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ─── Data Quality View ───────────────────────────────────────────────────────

function DataQualityView({ connectionId, tables }: { connectionId: string; tables: [string, TableInfo][] }) {
  const { data: statsData, isLoading } = useQuery({
    queryKey: ["schema-stats", connectionId],
    queryFn: () => api.get<{ tables: TableStat[] }>(`/schema/${connectionId}/stats`),
    enabled: !!connectionId,
  });

  const issues = useMemo(() => {
    const result: { table: string; severity: "error" | "warning" | "info"; message: string }[] = [];
    const statsMap: Record<string, TableStat> = {};
    for (const t of statsData?.tables ?? []) statsMap[t.table_name] = t;

    for (const [name, info] of tables) {
      const stat = statsMap[name];
      const cols = Object.entries(info.columns);

      // No primary key
      if (stat && !stat.has_primary_key) {
        result.push({ table: name, severity: "error", message: "No primary key — rows cannot be uniquely identified" });
      }
      // No indexes at all (except if tiny table)
      if (stat && stat.index_count === 0 && stat.row_count_estimate > 1000) {
        result.push({ table: name, severity: "warning", message: "No indexes — queries may be slow on large data" });
      }
      // All columns nullable
      const nonNullable = cols.filter(([, c]) => !c.nullable && !c.primary_key).length;
      if (nonNullable === 0 && cols.length > 2) {
        result.push({ table: name, severity: "warning", message: "All columns are nullable — consider adding NOT NULL constraints" });
      }
      // Very wide table
      if (cols.length > 40) {
        result.push({ table: name, severity: "info", message: `Wide table (${cols.length} cols) — consider normalization` });
      }
      // Tables with no rows
      if (stat && stat.row_count_estimate === 0) {
        result.push({ table: name, severity: "info", message: "Table appears empty" });
      }
    }
    return result;
  }, [tables, statsData]);

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warnCount = issues.filter((i) => i.severity === "warning").length;
  const infoCount = issues.filter((i) => i.severity === "info").length;

  // Coverage heatmap data
  const tableStats = statsData?.tables ?? [];
  const pkCoverage = tableStats.length > 0 ? Math.round((tableStats.filter((t) => t.has_primary_key).length / tableStats.length) * 100) : null;

  if (isLoading) return (
    <Card className="p-12">
      <div className="flex items-center justify-center gap-3">
        <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
        <span className="text-sm text-slate-400">Running quality checks…</span>
      </div>
    </Card>
  );

  return (
    <div className="space-y-5">
      {/* Summary scorecard */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3">
          <div className="flex items-center gap-2 mb-1">
            <XCircle className="h-4 w-4 text-red-400" />
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">Errors</span>
          </div>
          <p className={cn("text-lg font-bold", errorCount > 0 ? "text-red-400" : "text-white")}>{errorCount}</p>
        </Card>
        <Card className="p-3">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">Warnings</span>
          </div>
          <p className={cn("text-lg font-bold", warnCount > 0 ? "text-amber-400" : "text-white")}>{warnCount}</p>
        </Card>
        <Card className="p-3">
          <div className="flex items-center gap-2 mb-1">
            <Info className="h-4 w-4 text-blue-400" />
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">Suggestions</span>
          </div>
          <p className="text-lg font-bold text-white">{infoCount}</p>
        </Card>
        <Card className="p-3">
          <div className="flex items-center gap-2 mb-1">
            <Key className="h-4 w-4 text-violet-400" />
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">PK Coverage</span>
          </div>
          <p className={cn("text-lg font-bold", pkCoverage !== null && pkCoverage < 70 ? "text-amber-400" : "text-emerald-400")}>
            {pkCoverage !== null ? `${pkCoverage}%` : "—"}
          </p>
        </Card>
      </div>

      {/* Issue list */}
      {issues.length === 0 ? (
        <Card className="p-10">
          <div className="text-center">
            <CheckCircle2 className="h-10 w-10 text-emerald-400 mx-auto mb-3" />
            <p className="text-sm font-semibold text-emerald-300">All quality checks passed!</p>
            <p className="text-xs text-slate-500 mt-1">No structural issues detected across {tables.length} tables.</p>
          </div>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="px-4 py-2.5 bg-slate-800/30 border-b border-slate-700/20 flex items-center justify-between">
            <span className="text-sm font-semibold text-white flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-400" />
              Quality Issues ({issues.length})
            </span>
            <span className="text-[10px] text-slate-500">Sorted by severity</span>
          </div>
          <div className="divide-y divide-slate-700/15">
            {[...issues].sort((a, b) => {
              const order = { error: 0, warning: 1, info: 2 };
              return order[a.severity] - order[b.severity];
            }).map((issue, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-3 hover:bg-slate-800/20 transition-colors">
                <div className="shrink-0 mt-0.5">
                  {issue.severity === "error" ? <XCircle className="h-4 w-4 text-red-400" /> :
                   issue.severity === "warning" ? <AlertTriangle className="h-4 w-4 text-amber-400" /> :
                   <Info className="h-4 w-4 text-blue-400" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-slate-200 font-mono">{issue.table}</span>
                    <span className={cn("text-[9px] font-semibold px-1.5 py-0.5 rounded border",
                      issue.severity === "error" ? "text-red-400 bg-red-500/10 border-red-500/20" :
                      issue.severity === "warning" ? "text-amber-400 bg-amber-500/10 border-amber-500/20" :
                      "text-blue-400 bg-blue-500/10 border-blue-500/20")}>
                      {issue.severity.toUpperCase()}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{issue.message}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Per-table health heatmap */}
      {tableStats.length > 0 && (
        <Card className="overflow-hidden">
          <div className="px-4 py-2.5 bg-slate-800/30 border-b border-slate-700/20">
            <span className="text-sm font-semibold text-white flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-blue-400" />Table Health Heatmap
            </span>
          </div>
          <div className="p-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
            {tableStats.map((t) => {
              const score = tableHealthScore(t);
              const bg = score >= 80 ? "bg-emerald-500/15 border-emerald-500/20" : score >= 50 ? "bg-amber-500/15 border-amber-500/20" : "bg-red-500/15 border-red-500/20";
              const text = score >= 80 ? "text-emerald-300" : score >= 50 ? "text-amber-300" : "text-red-300";
              return (
                <div key={t.table_name} className={cn("rounded-lg border p-2.5 flex flex-col gap-1", bg)}>
                  <span className="text-[10px] font-mono text-slate-300 truncate">{t.table_name}</span>
                  <span className={cn("text-lg font-bold leading-none", text)}>{score}</span>
                  <span className="text-[9px] text-slate-500">{score >= 80 ? "Healthy" : score >= 50 ? "Fair" : "Needs work"}</span>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

// ─── Governance View ─────────────────────────────────────────────────────────

const GOV_STORAGE_KEY = "sbi_governance_map";

function GovernanceView({ tables }: { tables: [string, TableInfo][] }) {
  // Local persistence via localStorage until a backend endpoint is wired
  const [govMap, setGovMap] = useState<GovernanceMap>(() => {
    try { return JSON.parse(localStorage.getItem(GOV_STORAGE_KEY) ?? "{}"); } catch { return {}; }
  });
  const [editingCell, setEditingCell] = useState<{ table: string; col: string; field: keyof ColumnGovernance } | null>(null);
  const [editValue, setEditValue] = useState<string>("");
  const [expandedTable, setExpandedTable] = useState<string | null>(tables[0]?.[0] ?? null);

  const saveGov = (updated: GovernanceMap) => {
    setGovMap(updated);
    try { localStorage.setItem(GOV_STORAGE_KEY, JSON.stringify(updated)); } catch {}
    toast.success("Governance metadata saved");
  };

  const getCol = (table: string, col: string): ColumnGovernance => ({
    description: "", pii: false, sensitivity: "internal", owner: "", tags: [],
    ...govMap[table]?.[col],
  });

  const updateCol = (table: string, col: string, patch: Partial<ColumnGovernance>) => {
    const updated = {
      ...govMap,
      [table]: { ...govMap[table], [col]: { ...getCol(table, col), ...patch } },
    };
    saveGov(updated);
  };

  const startEdit = (table: string, col: string, field: keyof ColumnGovernance, current: string) => {
    setEditingCell({ table, col, field });
    setEditValue(current);
  };

  const commitEdit = () => {
    if (!editingCell) return;
    if (editingCell.field === "tags") {
      updateCol(editingCell.table, editingCell.col, { tags: editValue.split(",").map((t) => t.trim()).filter(Boolean) });
    } else {
      updateCol(editingCell.table, editingCell.col, { [editingCell.field]: editValue });
    }
    setEditingCell(null);
  };

  const piiCount = Object.values(govMap).flatMap(Object.values).filter((c: any) => c.pii).length;
  const describedCount = Object.values(govMap).flatMap(Object.values).filter((c: any) => c.description).length;
  const totalCols = tables.reduce((s, [, t]) => s + Object.keys(t.columns).length, 0);

  return (
    <div className="space-y-5">
      {/* Header stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card className="p-3">
          <div className="flex items-center gap-2 mb-1"><Tag className="h-4 w-4 text-blue-400" /><span className="text-[10px] text-slate-500 uppercase tracking-wider">Described</span></div>
          <p className="text-lg font-bold text-white">{describedCount}<span className="text-sm text-slate-500 font-normal ml-1">/ {totalCols}</span></p>
        </Card>
        <Card className="p-3">
          <div className="flex items-center gap-2 mb-1"><Lock className="h-4 w-4 text-red-400" /><span className="text-[10px] text-slate-500 uppercase tracking-wider">PII Tagged</span></div>
          <p className={cn("text-lg font-bold", piiCount > 0 ? "text-red-400" : "text-white")}>{piiCount}</p>
        </Card>
        <Card className="p-3 col-span-2 md:col-span-1">
          <div className="flex items-center gap-2 mb-1"><Shield className="h-4 w-4 text-violet-400" /><span className="text-[10px] text-slate-500 uppercase tracking-wider">Coverage</span></div>
          <p className="text-lg font-bold text-white">
            {totalCols > 0 ? `${Math.round((describedCount / totalCols) * 100)}%` : "—"}
          </p>
        </Card>
      </div>

      <div className="text-xs text-slate-500 flex items-center gap-1.5 bg-slate-800/30 rounded-lg px-3 py-2 border border-slate-700/30">
        <Info className="h-3.5 w-3.5 text-blue-400 shrink-0" />
        Governance metadata is stored locally. Wire to <code className="text-blue-300 font-mono">POST /schema/{"{conn}"}/governance</code> to persist server-side.
      </div>

      {/* Per-table governance editor */}
      {tables.map(([tableName, tableInfo]) => {
        const cols = Object.entries(tableInfo.columns);
        const isExpanded = expandedTable === tableName;
        const tablePiiCount = cols.filter(([, ]) => getCol(tableName, cols[0]?.[0] ?? "").pii).length;

        return (
          <Card key={tableName} className="overflow-hidden">
            <button
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/30 transition-colors"
              onClick={() => setExpandedTable(isExpanded ? null : tableName)}
            >
              <span className="text-slate-500">{isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</span>
              <Table2 className="h-3.5 w-3.5 text-blue-400 shrink-0" />
              <span className="text-sm font-semibold text-slate-200 font-mono">{tableName}</span>
              <span className="text-[10px] text-slate-500">{cols.length} columns</span>
              <div className="flex-1" />
              {cols.some(([col]) => getCol(tableName, col).pii) && (
                <span className="text-[9px] text-red-400 bg-red-500/10 border border-red-500/20 rounded px-1.5 py-0.5 flex items-center gap-1">
                  <Lock className="h-2.5 w-2.5" />Contains PII
                </span>
              )}
            </button>

            {isExpanded && (
              <div className="border-t border-slate-700/20 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-800/40 border-b border-slate-700/20">
                      {["Column", "Type", "Description", "Owner", "Sensitivity", "PII", "Tags"].map((h) => (
                        <th key={h} className="text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-3 py-2 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/15">
                    {cols.map(([colName, colInfo]) => {
                      const gov = getCol(tableName, colName);
                      const isEditingDesc = editingCell?.table === tableName && editingCell.col === colName && editingCell.field === "description";
                      const isEditingOwner = editingCell?.table === tableName && editingCell.col === colName && editingCell.field === "owner";
                      const isEditingTags = editingCell?.table === tableName && editingCell.col === colName && editingCell.field === "tags";

                      return (
                        <tr key={colName} className="hover:bg-slate-800/20 transition-colors">
                          {/* Column name */}
                          <td className="px-3 py-2 text-xs text-slate-300 font-mono whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              {colInfo.primary_key && <Key className="h-3 w-3 text-amber-400" />}
                              {gov.pii && <Lock className="h-3 w-3 text-red-400" />}
                              {colName}
                            </div>
                          </td>
                          {/* Type */}
                          <td className="px-3 py-2">
                            <span className={cn("text-[9px] px-1.5 py-0.5 rounded border whitespace-nowrap", getTypeBadgeColor(colInfo.type))}>{colInfo.type}</span>
                          </td>
                          {/* Description */}
                          <td className="px-3 py-2 min-w-[180px]">
                            {isEditingDesc ? (
                              <div className="flex items-center gap-1">
                                <input autoFocus value={editValue} onChange={(e) => setEditValue(e.target.value)}
                                  onKeyDown={(e) => { if (e.key === "Enter") commitEdit(); if (e.key === "Escape") setEditingCell(null); }}
                                  className="flex-1 text-xs bg-slate-700/50 border border-blue-500/40 rounded px-2 py-1 text-white focus:outline-none min-w-0" />
                                <button onClick={commitEdit} className="p-1 text-emerald-400 hover:text-emerald-300"><Check className="h-3 w-3" /></button>
                                <button onClick={() => setEditingCell(null)} className="p-1 text-slate-500 hover:text-slate-300"><X className="h-3 w-3" /></button>
                              </div>
                            ) : (
                              <button onClick={() => startEdit(tableName, colName, "description", gov.description)}
                                className="group flex items-center gap-1.5 text-left text-xs w-full hover:text-blue-300 transition-colors">
                                {gov.description
                                  ? <span className="text-slate-300">{gov.description}</span>
                                  : <span className="text-slate-600 italic">Add description…</span>}
                                <Edit3 className="h-2.5 w-2.5 text-slate-600 opacity-0 group-hover:opacity-100 shrink-0" />
                              </button>
                            )}
                          </td>
                          {/* Owner */}
                          <td className="px-3 py-2">
                            {isEditingOwner ? (
                              <div className="flex items-center gap-1">
                                <input autoFocus value={editValue} onChange={(e) => setEditValue(e.target.value)}
                                  onKeyDown={(e) => { if (e.key === "Enter") commitEdit(); if (e.key === "Escape") setEditingCell(null); }}
                                  className="w-24 text-xs bg-slate-700/50 border border-blue-500/40 rounded px-2 py-1 text-white focus:outline-none" />
                                <button onClick={commitEdit} className="p-1 text-emerald-400"><Check className="h-3 w-3" /></button>
                              </div>
                            ) : (
                              <button onClick={() => startEdit(tableName, colName, "owner", gov.owner)}
                                className="group flex items-center gap-1 text-xs hover:text-blue-300 transition-colors">
                                {gov.owner ? <span className="text-slate-400 font-mono">{gov.owner}</span> : <span className="text-slate-600 italic">—</span>}
                                <Edit3 className="h-2.5 w-2.5 text-slate-600 opacity-0 group-hover:opacity-100" />
                              </button>
                            )}
                          </td>
                          {/* Sensitivity */}
                          <td className="px-3 py-2">
                            <select
                              value={gov.sensitivity}
                              onChange={(e) => updateCol(tableName, colName, { sensitivity: e.target.value as ColumnGovernance["sensitivity"] })}
                              className="text-[10px] bg-slate-800/60 border border-slate-700/40 rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500/30 cursor-pointer"
                            >
                              {["public", "internal", "confidential", "restricted"].map((s) => (
                                <option key={s} value={s}>{s}</option>
                              ))}
                            </select>
                          </td>
                          {/* PII toggle */}
                          <td className="px-3 py-2">
                            <button
                              onClick={() => updateCol(tableName, colName, { pii: !gov.pii })}
                              className={cn("w-8 h-4 rounded-full transition-all duration-200 relative",
                                gov.pii ? "bg-red-500/70" : "bg-slate-700/60")}
                            >
                              <span className={cn("absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all duration-200",
                                gov.pii ? "left-4.5 translate-x-0" : "left-0.5")} />
                            </button>
                          </td>
                          {/* Tags */}
                          <td className="px-3 py-2">
                            {isEditingTags ? (
                              <div className="flex items-center gap-1">
                                <input autoFocus value={editValue} onChange={(e) => setEditValue(e.target.value)}
                                  placeholder="tag1, tag2…"
                                  onKeyDown={(e) => { if (e.key === "Enter") commitEdit(); if (e.key === "Escape") setEditingCell(null); }}
                                  className="w-28 text-xs bg-slate-700/50 border border-blue-500/40 rounded px-2 py-1 text-white focus:outline-none" />
                                <button onClick={commitEdit} className="p-1 text-emerald-400"><Check className="h-3 w-3" /></button>
                              </div>
                            ) : (
                              <button onClick={() => startEdit(tableName, colName, "tags", gov.tags.join(", "))}
                                className="group flex items-center gap-1 text-xs hover:text-blue-300 transition-colors flex-wrap">
                                {gov.tags.length > 0
                                  ? gov.tags.map((tag, i) => <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 text-blue-400">{tag}</span>)
                                  : <span className="text-slate-600 italic">+ tags</span>}
                                <Edit3 className="h-2.5 w-2.5 text-slate-600 opacity-0 group-hover:opacity-100 shrink-0" />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

// ─── Profile Panel ───────────────────────────────────────────────────────────

function ProfilePanel({ connectionId, tableName, onClose }: { connectionId: string; tableName: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["schema-profile", connectionId, tableName],
    queryFn: () => api.get<{ table_name: string; row_count: number; columns: ColumnProfile[] }>(`/schema/${connectionId}/profile/${tableName}`),
    enabled: !!connectionId && !!tableName,
  });
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-800/30 border-b border-slate-700/20">
        <span className="text-sm font-medium text-white flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-blue-400" />
          Profile: <span className="font-mono text-blue-300">{tableName}</span>
          {data && <span className="text-xs text-slate-500 ml-2">({data.row_count.toLocaleString()} rows)</span>}
        </span>
        <button onClick={onClose} className="text-slate-500 hover:text-white text-xs border border-slate-700/30 rounded px-2 py-1 hover:bg-slate-700/30 transition-colors">Close</button>
      </div>
      {isLoading && <div className="p-8 text-center"><Loader2 className="h-5 w-5 text-blue-400 animate-spin mx-auto" /><p className="text-sm text-slate-500 mt-2">Profiling columns…</p></div>}
      {error && <div className="p-4"><Alert variant="error">Failed to profile table</Alert></div>}
      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-800/40 border-b border-slate-700/20">
                {["Column", "Type", "Nulls %", "Distinct", "Min", "Max", "Samples", "Flags"].map((h) => (
                  <th key={h} className="text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-3 py-2">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/15">
              {data.columns.map((col) => {
                const highNull = col.null_pct > 50;
                const lowDistinct = col.distinct_count < 3 && data.row_count > 100;
                return (
                  <tr key={col.column_name} className="hover:bg-slate-800/20 transition-colors">
                    <td className="px-3 py-2 text-xs text-slate-300 font-mono">{col.column_name}</td>
                    <td className="px-3 py-2"><span className={cn("text-[9px] px-1.5 py-0.5 rounded border", getTypeBadgeColor(col.data_type))}>{col.data_type}</span></td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1.5 rounded-full bg-slate-700/50 overflow-hidden">
                          <div className={cn("h-full rounded-full transition-all", col.null_pct > 50 ? "bg-red-500" : col.null_pct > 20 ? "bg-amber-500" : "bg-emerald-500")}
                            style={{ width: `${Math.min(col.null_pct, 100)}%` }} />
                        </div>
                        <span className="text-[10px] text-slate-500">{col.null_pct}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-400 font-mono">{col.distinct_count.toLocaleString()}</td>
                    <td className="px-3 py-2 text-[10px] text-slate-500 font-mono max-w-[100px] truncate">{col.min_value ?? "—"}</td>
                    <td className="px-3 py-2 text-[10px] text-slate-500 font-mono max-w-[100px] truncate">{col.max_value ?? "—"}</td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {col.sample_values.slice(0, 3).map((v, i) => (
                          <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-700/30 text-slate-400 font-mono max-w-[80px] truncate">{v}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {highNull && <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 border border-red-500/20 text-red-400">High null</span>}
                        {lowDistinct && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400">Low cardinality</span>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function SchemaPage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "admin" || user?.role === "ceo";
  const [selectedConnection, setSelectedConnection] = useState("");
  const [tableSearch, setTableSearch] = useState("");
  const [activeTab, setActiveTab] = useState<TabId>("browse");
  const [profileTable, setProfileTable] = useState<string | null>(null);

  const { data: connData } = useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnectionListResponse>("/connections/") });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];
  if (connections.length > 0 && !selectedConnection) setSelectedConnection(connections[0].connection_id);

  const { data: schema, isLoading, error, refetch } = useQuery({
    queryKey: ["schema", selectedConnection],
    queryFn: () => api.get<SchemaResponse>(`/schema/${selectedConnection}`),
    enabled: !!selectedConnection,
  });
  const { data: statsData } = useQuery({
    queryKey: ["schema-stats", selectedConnection],
    queryFn: () => api.get<{ tables: TableStat[] }>(`/schema/${selectedConnection}/stats`),
    enabled: !!selectedConnection && activeTab !== "stats",
  });
  const statsMap = useMemo(() => {
    const map: Record<string, TableStat> = {};
    for (const t of statsData?.tables ?? []) map[t.table_name] = t;
    return map;
  }, [statsData]);

  const refreshMutation = useMutation({
    mutationFn: () => api.post<SchemaRefreshResponse>(`/schema/${selectedConnection}/refresh`),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["schema", selectedConnection] });
      queryClient.invalidateQueries({ queryKey: ["schema-stats", selectedConnection] });
      queryClient.invalidateQueries({ queryKey: ["schema-relationships", selectedConnection] });
      toast.success(`Cache cleared (${data.keys_deleted} keys). Refreshing…`);
      refetch();
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const tables = schema?.schema_data ? Object.entries(schema.schema_data) : [];
  const filteredTables = tableSearch
    ? tables.filter(([name]) => name.toLowerCase().includes(tableSearch.toLowerCase()))
    : tables;
  const totalTables = tables.length;
  const totalColumns = tables.reduce((sum, [, info]) => sum + Object.keys(info.columns).length, 0);

  const TABS: { id: TabId; label: string; icon: React.ReactNode; adminOnly?: boolean }[] = [
    { id: "browse",        label: "Browse",        icon: <Database className="h-3.5 w-3.5" /> },
    { id: "relationships", label: "Relationships",  icon: <GitBranch className="h-3.5 w-3.5" /> },
    { id: "stats",         label: "Statistics",    icon: <Activity className="h-3.5 w-3.5" /> },
    { id: "quality",       label: "Data Quality",  icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
    { id: "governance",    label: "Governance",    icon: <Shield className="h-3.5 w-3.5" />, adminOnly: true },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <HardDrive className="h-6 w-6 text-blue-400" />
            Schema Browser
          </h1>
          <p className="text-sm text-slate-400 mt-1">Explore tables, relationships, data quality and governance</p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && selectedConnection && (
            <Button variant="secondary" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => refreshMutation.mutate()} isLoading={refreshMutation.isPending}>
              Refresh Cache
            </Button>
          )}
        </div>
      </div>

      {/* Connection Selector */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1">
          <Database className="h-4 w-4 text-slate-500 shrink-0" />
          <select value={selectedConnection}
            onChange={(e) => { setSelectedConnection(e.target.value); setTableSearch(""); setProfileTable(null); }}
            className="flex-1 h-9 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-300 text-sm px-3 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500/40 transition-colors">
            <option value="" disabled>Select a database connection…</option>
            {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name} ({c.db_type})</option>)}
          </select>
        </div>
        {schema && (
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 shrink-0">
            <Timer className="h-3 w-3" />
            {schema.cached
              ? <span>Cached{schema.cache_age_seconds != null && <span className="text-slate-600 ml-0.5">({schema.cache_age_seconds}s ago)</span>}</span>
              : <span className="text-emerald-400">Fresh</span>}
          </div>
        )}
      </div>

      {/* Tabs */}
      {selectedConnection && (
        <div className="flex items-center gap-1 border-b border-slate-700/30 pb-0 overflow-x-auto">
          {TABS.filter((tab) => !tab.adminOnly || isAdmin).map((tab) => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={cn("flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-all -mb-[1px] whitespace-nowrap",
                activeTab === tab.id
                  ? "text-blue-400 border-blue-500"
                  : "text-slate-500 border-transparent hover:text-slate-300 hover:border-slate-600"
              )}>
              {tab.icon}{tab.label}
            </button>
          ))}
        </div>
      )}

      {error && <Alert variant="error">{error instanceof ApiRequestError ? error.message : "Failed to load schema"}</Alert>}
      {isLoading && selectedConnection && (
        <Card className="p-12"><div className="flex items-center justify-center gap-3"><Loader2 className="h-5 w-5 text-blue-400 animate-spin" /><span className="text-sm text-slate-400">Introspecting database schema…</span></div></Card>
      )}
      {!selectedConnection && (
        <Card className="p-12"><div className="text-center"><Database className="h-8 w-8 text-slate-600 mx-auto mb-3" /><p className="text-sm text-slate-400 font-medium">Select a connection to browse its schema</p></div></Card>
      )}

      {schema && !isLoading && (
        <>
          {/* BROWSE */}
          {activeTab === "browse" && (
            <>
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-4 text-xs text-slate-500">
                  <span className="flex items-center gap-1"><Table2 className="h-3 w-3" />{totalTables} table{totalTables !== 1 ? "s" : ""}</span>
                  <span className="flex items-center gap-1"><Columns3 className="h-3 w-3" />{totalColumns} column{totalColumns !== 1 ? "s" : ""}</span>
                </div>
                {totalTables > 5 && (
                  <div className="w-64">
                    <Input placeholder="Filter tables…" value={tableSearch} onChange={(e) => setTableSearch(e.target.value)} icon={<Search className="h-3.5 w-3.5" />} />
                  </div>
                )}
              </div>
              {profileTable && <ProfilePanel connectionId={selectedConnection} tableName={profileTable} onClose={() => setProfileTable(null)} />}
              {totalTables === 0 && <Card className="p-12"><div className="text-center"><Table2 className="h-8 w-8 text-slate-600 mx-auto mb-3" /><p className="text-sm text-slate-400 font-medium">No tables found</p></div></Card>}
              {totalTables > 0 && filteredTables.length === 0 && <Card className="p-8"><div className="text-center"><Search className="h-6 w-6 text-slate-600 mx-auto mb-2" /><p className="text-sm text-slate-400">No tables match &quot;{tableSearch}&quot;</p></div></Card>}
              {filteredTables.length > 0 && (
                <Card className="divide-y divide-slate-700/20 overflow-hidden">
                  {filteredTables.map(([name, info]) => (
                    <TableRow key={name} name={name} info={info} stats={statsMap[name]} onProfile={(t) => setProfileTable(t)} />
                  ))}
                </Card>
              )}
            </>
          )}
          {activeTab === "relationships" && <RelationshipsView connectionId={selectedConnection} />}
          {activeTab === "stats" && <StatsView connectionId={selectedConnection} />}
          {activeTab === "quality" && <DataQualityView connectionId={selectedConnection} tables={tables} />}
          {activeTab === "governance" && isAdmin && <GovernanceView tables={tables} />}
        </>
      )}
    </div>
  );
}
