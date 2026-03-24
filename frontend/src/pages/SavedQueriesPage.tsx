/**
 * Smart BI Agent — Saved Queries Page
 * Phase 4D | All authenticated users (ownership enforced by backend)
 *
 * Library of saved queries with sensitivity badges, pin/share toggles,
 * SQL preview, and re-run support.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import {
  Bookmark,
  Pin,
  Share2,
  Copy,
  Trash2,
  Eye,
  Search,
  RefreshCw,
  Loader2,
  X,
  Shield,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input } from "@/components/ui";
import type { SavedQuery, SavedQueryListResponse } from "@/types/saved-queries";

// ─── Sensitivity Badges ─────────────────────────────────────────────────────

const sensitivityConfig: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  normal: {
    label: "Normal",
    icon: <ShieldCheck className="h-3 w-3" />,
    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  },
  sensitive: {
    label: "Sensitive",
    icon: <Shield className="h-3 w-3" />,
    color: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  },
  restricted: {
    label: "Restricted",
    icon: <ShieldAlert className="h-3 w-3" />,
    color: "text-red-400 bg-red-500/10 border-red-500/20",
  },
};

// ─── Detail Modal ───────────────────────────────────────────────────────────

function QueryDetailModal({
  query,
  onClose,
}: {
  query: SavedQuery;
  onClose: () => void;
}) {
  const cfg = sensitivityConfig[query.sensitivity] ?? sensitivityConfig.normal;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-slate-700/40">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-white truncate">{query.name}</h2>
            <p className="text-sm text-slate-400 mt-0.5">{query.question}</p>
            <div className="flex items-center gap-2 mt-2">
              <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border inline-flex items-center gap-1", cfg.color)}>
                {cfg.icon} {cfg.label}
              </span>
              {query.is_shared && (
                <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border text-blue-400 bg-blue-500/10 border-blue-500/20">
                  Shared
                </span>
              )}
              {query.is_pinned && (
                <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border text-amber-400 bg-amber-500/10 border-amber-500/20">
                  Pinned
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* SQL Preview */}
        <div className="p-6">
          {query.description && (
            <p className="text-sm text-slate-400 mb-4">{query.description}</p>
          )}
          <div className="rounded-lg overflow-hidden border border-slate-700/40">
            <div className="h-[300px]">
              <Editor
                height="100%"
                defaultLanguage="sql"
                value={query.sql_query}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                  padding: { top: 12 },
                }}
              />
            </div>
          </div>

          {/* Metadata */}
          <div className="flex items-center gap-4 mt-4 text-xs text-slate-500">
            <span>Run {query.run_count} time{query.run_count !== 1 ? "s" : ""}</span>
            {query.last_run_at && (
              <span>Last run: {new Date(query.last_run_at).toLocaleDateString()}</span>
            )}
            {query.tags.length > 0 && (
              <span>Tags: {query.tags.join(", ")}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function SavedQueriesPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedQuery, setSelectedQuery] = useState<SavedQuery | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["saved-queries"],
    queryFn: () => api.get<SavedQueryListResponse>("/saved-queries/?limit=200"),
  });

  const togglePin = useMutation({
    mutationFn: (id: string) => api.patch(`/saved-queries/${id}/pin`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Pin toggled");
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const toggleShare = useMutation({
    mutationFn: (id: string) => api.patch(`/saved-queries/${id}/share`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Sharing toggled");
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const duplicate = useMutation({
    mutationFn: (id: string) => api.post(`/saved-queries/${id}/duplicate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Query duplicated");
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const deleteQuery = useMutation({
    mutationFn: (id: string) => api.delete(`/saved-queries/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      setDeletingId(null);
      toast.success("Query deleted");
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message);
      setDeletingId(null);
    },
  });

  const queries = data?.queries ?? [];
  const filtered = search
    ? queries.filter(
        (q) =>
          q.name.toLowerCase().includes(search.toLowerCase()) ||
          q.question.toLowerCase().includes(search.toLowerCase()) ||
          q.tags.some((t) => t.toLowerCase().includes(search.toLowerCase()))
      )
    : queries;

  // Sort: pinned first, then by name
  const sorted = [...filtered].sort((a, b) => {
    if (a.is_pinned && !b.is_pinned) return -1;
    if (!a.is_pinned && b.is_pinned) return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Saved Queries</h1>
          <p className="text-sm text-slate-400 mt-1">
            Your query library with sensitivity classification
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => refetch()}
          isLoading={isLoading}
        >
          Refresh
        </Button>
      </div>

      {/* Search */}
      <Input
        placeholder="Search by name, question, or tag…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        icon={<Search className="h-4 w-4" />}
      />

      {error && (
        <Alert variant="error">
          {error instanceof ApiRequestError ? error.message : "Failed to load queries"}
        </Alert>
      )}

      {/* Empty */}
      {!isLoading && !error && sorted.length === 0 && (
        <Card className="p-12">
          <div className="text-center">
            <Bookmark className="h-8 w-8 text-slate-600 mx-auto mb-3" />
            <h3 className="text-sm font-medium text-slate-300 mb-1">
              {search ? "No queries match your search" : "No saved queries yet"}
            </h3>
            <p className="text-xs text-slate-500">
              {search
                ? "Try different search terms"
                : "Save queries from the AI Query page to build your library"}
            </p>
          </div>
        </Card>
      )}

      {isLoading && (
        <Card className="p-12">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
            <span className="text-sm text-slate-400">Loading queries…</span>
          </div>
        </Card>
      )}

      {/* Query Cards Grid */}
      {sorted.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {sorted.map((q) => {
            const cfg = sensitivityConfig[q.sensitivity] ?? sensitivityConfig.normal;
            return (
              <Card
                key={q.query_id}
                className="p-4 hover:border-slate-600/80 transition-colors cursor-pointer"
              >
                {/* Top row: name + badges */}
                <div className="flex items-start justify-between mb-2">
                  <div
                    className="min-w-0 flex-1 cursor-pointer"
                    onClick={() => setSelectedQuery(q)}
                  >
                    <div className="flex items-center gap-2">
                      {q.is_pinned && <Pin className="h-3 w-3 text-amber-400 shrink-0" />}
                      <h3 className="text-sm font-medium text-slate-200 truncate">
                        {q.name}
                      </h3>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5 truncate">
                      {q.question}
                    </p>
                  </div>
                  <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border inline-flex items-center gap-1 shrink-0 ml-2", cfg.color)}>
                    {cfg.icon} {cfg.label}
                  </span>
                </div>

                {/* Actions row */}
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-700/30">
                  <div className="flex items-center gap-3 text-xs text-slate-500">
                    <span>Run {q.run_count}×</span>
                    {q.is_shared && (
                      <span className="text-blue-400 flex items-center gap-0.5">
                        <Share2 className="h-3 w-3" /> Shared
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-0.5">
                    <button
                      onClick={() => setSelectedQuery(q)}
                      className="p-1.5 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
                      title="View details"
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => togglePin.mutate(q.query_id)}
                      className={cn(
                        "p-1.5 rounded transition-colors",
                        q.is_pinned
                          ? "text-amber-400 hover:bg-amber-500/10"
                          : "text-slate-400 hover:text-amber-400 hover:bg-amber-500/10"
                      )}
                      title="Toggle pin"
                    >
                      <Pin className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => toggleShare.mutate(q.query_id)}
                      className={cn(
                        "p-1.5 rounded transition-colors",
                        q.is_shared
                          ? "text-blue-400 hover:bg-blue-500/10"
                          : "text-slate-400 hover:text-blue-400 hover:bg-blue-500/10"
                      )}
                      title="Toggle sharing"
                    >
                      <Share2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => duplicate.mutate(q.query_id)}
                      className="p-1.5 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
                      title="Duplicate"
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                    {deletingId === q.query_id ? (
                      <div className="flex items-center gap-1 ml-1">
                        <button
                          onClick={() => deleteQuery.mutate(q.query_id)}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-red-600/80 text-white hover:bg-red-500"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setDeletingId(null)}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeletingId(q.query_id)}
                        className="p-1.5 rounded text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Count */}
      {data && sorted.length > 0 && (
        <p className="text-xs text-slate-500 text-center">
          {sorted.length} of {data.total} quer{data.total !== 1 ? "ies" : "y"}
        </p>
      )}

      {/* Detail Modal */}
      {selectedQuery && (
        <QueryDetailModal
          query={selectedQuery}
          onClose={() => setSelectedQuery(null)}
        />
      )}
    </div>
  );
}
