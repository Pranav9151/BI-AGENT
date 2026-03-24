/**
 * Smart BI Agent — Schema Browser Page
 * Phase 5 | Session 2
 *
 * Features:
 *   - Connection selector
 *   - Tree view: Connection → Tables → Columns
 *   - Column badges: type, PK, nullable
 *   - Click table name → copies to clipboard
 *   - Schema refresh button (admin only) → invalidates Redis cache
 *   - Cache status indicator
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Database,
  Table2,
  Columns3,
  Key,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  Copy,
  Check,
  Search,
  Loader2,
  Timer,
  HardDrive,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { Button, Card, Alert, Input } from "@/components/ui";
import type { ConnectionListResponse } from "@/types/connections";
import type { SchemaResponse, SchemaRefreshResponse, TableInfo, ColumnInfo } from "@/types/schema";

// ─── Type Badge Colors ──────────────────────────────────────────────────────

function getTypeBadgeColor(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("int") || t.includes("numeric") || t.includes("decimal") || t.includes("float") || t.includes("double") || t.includes("real"))
    return "text-blue-400 bg-blue-500/10 border-blue-500/20";
  if (t.includes("char") || t.includes("text") || t.includes("string") || t.includes("varchar"))
    return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
  if (t.includes("date") || t.includes("time") || t.includes("interval"))
    return "text-amber-400 bg-amber-500/10 border-amber-500/20";
  if (t.includes("bool"))
    return "text-violet-400 bg-violet-500/10 border-violet-500/20";
  if (t.includes("uuid") || t.includes("json") || t.includes("array"))
    return "text-cyan-400 bg-cyan-500/10 border-cyan-500/20";
  return "text-slate-400 bg-slate-500/10 border-slate-500/20";
}

// ─── Copy Table Name Button ─────────────────────────────────────────────────

function CopyTableButton({ tableName }: { tableName: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(tableName);
    setCopied(true);
    toast.success(`Copied "${tableName}" to clipboard`);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
      title="Copy table name"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

// ─── Table Row ──────────────────────────────────────────────────────────────

function TableRow({ name, info }: { name: string; info: TableInfo }) {
  const [expanded, setExpanded] = useState(false);
  const columns = Object.entries(info.columns);
  const pkCount = columns.filter(([, c]) => c.primary_key).length;

  return (
    <div className="border-b border-slate-700/20 last:border-b-0">
      {/* Table header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-slate-800/40 transition-colors group"
      >
        <span className="text-slate-500 shrink-0">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
        <Table2 className="h-3.5 w-3.5 text-blue-400 shrink-0" />
        <span className="text-sm font-medium text-slate-200 font-mono">{name}</span>
        <span className="text-[10px] text-slate-500 ml-1">
          {columns.length} col{columns.length !== 1 ? "s" : ""}
          {pkCount > 0 && <span className="text-amber-500 ml-1.5">· {pkCount} PK</span>}
        </span>
        <div className="flex-1" />
        <CopyTableButton tableName={name} />
      </button>

      {/* Columns */}
      {expanded && columns.length > 0 && (
        <div className="bg-slate-800/20 border-t border-slate-700/20">
          {columns.map(([colName, colInfo]) => (
            <ColumnRow key={colName} name={colName} info={colInfo} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Column Row ─────────────────────────────────────────────────────────────

function ColumnRow({ name, info }: { name: string; info: ColumnInfo }) {
  const typeBadge = getTypeBadgeColor(info.type);

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 pl-12 hover:bg-slate-700/20 transition-colors">
      <Columns3 className="h-3 w-3 text-slate-600 shrink-0" />
      <span className="text-xs text-slate-300 font-mono min-w-0 truncate">{name}</span>

      {/* Badges */}
      <div className="flex items-center gap-1.5 ml-auto shrink-0">
        {info.primary_key && (
          <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded border text-amber-400 bg-amber-500/10 border-amber-500/20">
            <Key className="h-2.5 w-2.5" />PK
          </span>
        )}
        <span className={cn("text-[9px] font-medium px-1.5 py-0.5 rounded border", typeBadge)}>
          {info.type}
        </span>
        {info.nullable && (
          <span className="text-[9px] font-medium px-1.5 py-0.5 rounded border text-slate-500 bg-slate-500/5 border-slate-600/30">
            null
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function SchemaPage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "admin";
  const [selectedConnection, setSelectedConnection] = useState("");
  const [tableSearch, setTableSearch] = useState("");

  // Load connections
  const { data: connData } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionListResponse>("/connections/"),
  });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];

  // Auto-select first connection
  if (connections.length > 0 && !selectedConnection) {
    setSelectedConnection(connections[0].connection_id);
  }

  // Load schema for selected connection
  const {
    data: schema,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["schema", selectedConnection],
    queryFn: () => api.get<SchemaResponse>(`/schema/${selectedConnection}`),
    enabled: !!selectedConnection,
  });

  // Admin refresh
  const refreshMutation = useMutation({
    mutationFn: () =>
      api.post<SchemaRefreshResponse>(`/schema/${selectedConnection}/refresh`),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["schema", selectedConnection] });
      toast.success(`Cache cleared (${data.keys_deleted} key${data.keys_deleted !== 1 ? "s" : ""} deleted). Refreshing…`);
      refetch();
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  // Process tables
  const tables = schema?.schema_data
    ? Object.entries(schema.schema_data)
    : [];

  const filteredTables = tableSearch
    ? tables.filter(([name]) =>
        name.toLowerCase().includes(tableSearch.toLowerCase())
      )
    : tables;

  // Stats
  const totalTables = tables.length;
  const totalColumns = tables.reduce(
    (sum, [, info]) => sum + Object.keys(info.columns).length,
    0
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <HardDrive className="h-6 w-6 text-blue-400" />
            Schema Browser
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Explore database tables and columns
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && selectedConnection && (
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => refreshMutation.mutate()}
              isLoading={refreshMutation.isPending}
            >
              Refresh Cache
            </Button>
          )}
        </div>
      </div>

      {/* Connection Selector */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1">
          <Database className="h-4 w-4 text-slate-500 shrink-0" />
          <select
            value={selectedConnection}
            onChange={(e) => {
              setSelectedConnection(e.target.value);
              setTableSearch("");
            }}
            className="flex-1 h-9 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-300 text-sm px-3 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500/40 transition-colors"
          >
            <option value="" disabled>
              Select a database connection…
            </option>
            {connections.map((c) => (
              <option key={c.connection_id} value={c.connection_id}>
                {c.name} ({c.db_type})
              </option>
            ))}
          </select>
        </div>

        {/* Cache status */}
        {schema && (
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 shrink-0">
            <Timer className="h-3 w-3" />
            {schema.cached ? (
              <span>
                Cached
                {schema.cache_age_seconds != null && (
                  <span className="text-slate-600 ml-0.5">
                    ({schema.cache_age_seconds}s ago)
                  </span>
                )}
              </span>
            ) : (
              <span className="text-emerald-400">Fresh</span>
            )}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <Alert variant="error">
          {error instanceof ApiRequestError
            ? error.message
            : "Failed to load schema"}
        </Alert>
      )}

      {/* Loading */}
      {isLoading && selectedConnection && (
        <Card className="p-12">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
            <span className="text-sm text-slate-400">
              Introspecting database schema…
            </span>
          </div>
        </Card>
      )}

      {/* No connection selected */}
      {!selectedConnection && (
        <Card className="p-12">
          <div className="text-center">
            <Database className="h-8 w-8 text-slate-600 mx-auto mb-3" />
            <p className="text-sm text-slate-400 font-medium">
              Select a connection to browse its schema
            </p>
          </div>
        </Card>
      )}

      {/* Schema loaded */}
      {schema && !isLoading && (
        <>
          {/* Stats + Search */}
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-4 text-xs text-slate-500">
              <span className="flex items-center gap-1">
                <Table2 className="h-3 w-3" />
                {totalTables} table{totalTables !== 1 ? "s" : ""}
              </span>
              <span className="flex items-center gap-1">
                <Columns3 className="h-3 w-3" />
                {totalColumns} column{totalColumns !== 1 ? "s" : ""}
              </span>
            </div>
            {totalTables > 5 && (
              <div className="w-64">
                <Input
                  placeholder="Filter tables…"
                  value={tableSearch}
                  onChange={(e) => setTableSearch(e.target.value)}
                  icon={<Search className="h-3.5 w-3.5" />}
                />
              </div>
            )}
          </div>

          {/* Empty schema */}
          {totalTables === 0 && (
            <Card className="p-12">
              <div className="text-center">
                <Table2 className="h-8 w-8 text-slate-600 mx-auto mb-3" />
                <p className="text-sm text-slate-400 font-medium">
                  No tables found
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  This database has no accessible tables in the allowed schemas
                </p>
              </div>
            </Card>
          )}

          {/* Filter empty */}
          {totalTables > 0 && filteredTables.length === 0 && (
            <Card className="p-8">
              <div className="text-center">
                <Search className="h-6 w-6 text-slate-600 mx-auto mb-2" />
                <p className="text-sm text-slate-400">
                  No tables match "{tableSearch}"
                </p>
              </div>
            </Card>
          )}

          {/* Table Tree */}
          {filteredTables.length > 0 && (
            <Card className="divide-y divide-slate-700/20 overflow-hidden">
              {filteredTables.map(([name, info]) => (
                <TableRow key={name} name={name} info={info} />
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}