/**
 * Smart BI Agent — Connections Page
 * Phase 4A | Admin only
 *
 * List all database connections with status indicators,
 * test connectivity, and CRUD actions.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Plug,
  PlugZap,
  Pencil,
  Trash2,
  Database,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert } from "@/components/ui";
import type {
  Connection,
  ConnectionListResponse,
  ConnectionTestResponse,
} from "@/types/connections";

// ─── DB Type Badges ─────────────────────────────────────────────────────────

const dbTypeConfig: Record<string, { label: string; color: string }> = {
  postgresql: { label: "PostgreSQL", color: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
  mysql:      { label: "MySQL",      color: "text-orange-400 bg-orange-500/10 border-orange-500/20" },
  mssql:      { label: "MSSQL",      color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20" },
  bigquery:   { label: "BigQuery",   color: "text-green-400 bg-green-500/10 border-green-500/20" },
  snowflake:  { label: "Snowflake",  color: "text-sky-400 bg-sky-500/10 border-sky-500/20" },
};

function DBTypeBadge({ type }: { type: string }) {
  const cfg = dbTypeConfig[type] ?? {
    label: type,
    color: "text-slate-400 bg-slate-500/10 border-slate-500/20",
  };
  return (
    <span
      className={cn(
        "text-[10px] font-medium px-2 py-0.5 rounded-full border inline-block",
        cfg.color
      )}
    >
      {cfg.label}
    </span>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={cn(
          "w-2 h-2 rounded-full shrink-0",
          active ? "bg-emerald-400" : "bg-slate-500"
        )}
      />
      <span className={cn("text-xs", active ? "text-emerald-400" : "text-slate-500")}>
        {active ? "Active" : "Inactive"}
      </span>
    </span>
  );
}

// ─── Test Button ────────────────────────────────────────────────────────────

function TestButton({ connectionId }: { connectionId: string }) {
  const [result, setResult] = useState<ConnectionTestResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post<ConnectionTestResponse>(
        `/connections/${connectionId}/test`
      ),
    onSuccess: (data) => {
      setResult(data);
      if (data.success) {
        toast.success(`Connected (${data.latency_ms}ms)`);
      } else {
        toast.error(data.error || "Connection failed");
      }
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Test failed");
    },
  });

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="text-slate-400 hover:text-blue-400 transition-colors disabled:opacity-50"
        title="Test connectivity"
      >
        {mutation.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <PlugZap className="h-4 w-4" />
        )}
      </button>
      {result && !mutation.isPending && (
        result.success ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-red-400" />
        )
      )}
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function ConnectionsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null);

  // Fetch connections
  const {
    data,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionListResponse>("/connections/"),
  });

  // Deactivate mutation (soft)
  const deactivate = useMutation({
    mutationFn: (id: string) => api.delete(`/connections/${id}`),
    onSuccess: () => {
      toast.success("Connection deactivated");
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setDeactivatingId(null);
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to deactivate");
      setDeactivatingId(null);
    },
  });

  // Hard delete mutation (permanent)
  const hardDelete = useMutation({
    mutationFn: (id: string) => api.delete(`/connections/${id}?permanent=true`),
    onSuccess: () => {
      toast.success("Connection permanently deleted");
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setDeactivatingId(null);
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to delete");
      setDeactivatingId(null);
    },
  });

  const connections = data?.connections ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Database Connections</h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage database connections with encrypted credentials
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => refetch()}
            isLoading={isLoading}
          >
            Refresh
          </Button>
          <Button
            size="sm"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => navigate("/connections/new")}
          >
            Add Connection
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <Alert variant="error">
          {error instanceof ApiRequestError
            ? error.message
            : "Failed to load connections"}
        </Alert>
      )}

      {/* Empty State */}
      {!isLoading && !error && connections.length === 0 && (
        <Card className="p-12">
          <div className="text-center">
            <div className="mx-auto w-12 h-12 rounded-full bg-slate-700/50 flex items-center justify-center mb-4">
              <Database className="h-6 w-6 text-slate-500" />
            </div>
            <h3 className="text-sm font-medium text-slate-300 mb-1">
              No connections yet
            </h3>
            <p className="text-xs text-slate-500 mb-4 max-w-sm mx-auto">
              Add your first database connection to start querying with AI.
              Credentials are encrypted at rest using HKDF.
            </p>
            <Button
              size="sm"
              icon={<Plus className="h-4 w-4" />}
              onClick={() => navigate("/connections/new")}
            >
              Add Connection
            </Button>
          </div>
        </Card>
      )}

      {/* Loading */}
      {isLoading && (
        <Card className="p-12">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
            <span className="text-sm text-slate-400">Loading connections…</span>
          </div>
        </Card>
      )}

      {/* Connections Table */}
      {connections.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/40">
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Name
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Type
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Host
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Database
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Status
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Test
                  </th>
                  <th className="text-right text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {connections.map((conn) => (
                  <tr
                    key={conn.connection_id}
                    className="hover:bg-slate-800/40 transition-colors"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2.5">
                        <Plug className="h-4 w-4 text-slate-500 shrink-0" />
                        <span className="text-sm font-medium text-slate-200 truncate max-w-[200px]">
                          {conn.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <DBTypeBadge type={conn.db_type} />
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-slate-400 font-mono">
                        {conn.host ?? "—"}
                        {conn.port ? `:${conn.port}` : ""}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-slate-400">
                        {conn.database_name ?? "—"}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <StatusDot active={conn.is_active} />
                    </td>
                    <td className="px-6 py-4">
                      <TestButton connectionId={conn.connection_id} />
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() =>
                            navigate(`/connections/${conn.connection_id}/edit`)
                          }
                          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
                          title="Edit"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        {deactivatingId === conn.connection_id ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => deactivate.mutate(conn.connection_id)}
                              className="text-[11px] px-2 py-1 rounded bg-amber-600/80 text-white hover:bg-amber-500 transition-colors"
                              disabled={deactivate.isPending || hardDelete.isPending}
                            >
                              Deactivate
                            </button>
                            <button
                              onClick={() => hardDelete.mutate(conn.connection_id)}
                              className="text-[11px] px-2 py-1 rounded bg-red-600/80 text-white hover:bg-red-500 transition-colors"
                              disabled={deactivate.isPending || hardDelete.isPending}
                            >
                              Delete
                            </button>
                            <button
                              onClick={() => setDeactivatingId(null)}
                              className="text-[11px] px-2 py-1 rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() =>
                              setDeactivatingId(conn.connection_id)
                            }
                            className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Deactivate"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Footer with count */}
          {data && (
            <div className="px-6 py-3 border-t border-slate-700/30 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                {data.total} connection{data.total !== 1 ? "s" : ""}
              </span>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
