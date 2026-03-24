/**
 * Smart BI Agent — LLM Providers Page
 * Phase 4B | Admin only
 *
 * List all LLM providers with status, test connectivity,
 * set-default, and CRUD actions.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Brain,
  Pencil,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
  Star,
  Zap,
  Shield,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert } from "@/components/ui";
import type {
  LLMProvider,
  LLMProviderListResponse,
  LLMProviderTestResponse,
  LLMProviderSetDefaultResponse,
} from "@/types/llm-providers";

// ─── Provider Type Badges ───────────────────────────────────────────────────

const providerConfig: Record<string, { label: string; color: string }> = {
  openai:   { label: "OpenAI",   color: "text-green-400 bg-green-500/10 border-green-500/20" },
  claude:   { label: "Claude",   color: "text-orange-400 bg-orange-500/10 border-orange-500/20" },
  gemini:   { label: "Gemini",   color: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
  groq:     { label: "Groq",     color: "text-purple-400 bg-purple-500/10 border-purple-500/20" },
  deepseek: { label: "DeepSeek", color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20" },
  ollama:   { label: "Ollama",   color: "text-slate-300 bg-slate-500/10 border-slate-500/20" },
};

const residencyConfig: Record<string, { label: string; color: string }> = {
  us:      { label: "US",      color: "text-blue-400" },
  eu:      { label: "EU",      color: "text-emerald-400" },
  cn:      { label: "CN",      color: "text-red-400" },
  local:   { label: "Local",   color: "text-amber-400" },
  unknown: { label: "Unknown", color: "text-slate-500" },
};

function ProviderBadge({ type }: { type: string }) {
  const cfg = providerConfig[type] ?? {
    label: type,
    color: "text-slate-400 bg-slate-500/10 border-slate-500/20",
  };
  return (
    <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border inline-block", cfg.color)}>
      {cfg.label}
    </span>
  );
}

// ─── Test Button ────────────────────────────────────────────────────────────

function TestButton({ providerId }: { providerId: string }) {
  const [result, setResult] = useState<LLMProviderTestResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post<LLMProviderTestResponse>(`/llm-providers/${providerId}/test`),
    onSuccess: (data) => {
      setResult(data);
      if (data.success) {
        toast.success(`Provider working (${data.latency_ms}ms, ${data.model_used})`);
      } else {
        toast.error(data.error || "Provider test failed");
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
        title="Test provider"
      >
        {mutation.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Zap className="h-4 w-4" />
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

export default function LLMProvidersPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["llm-providers"],
    queryFn: () => api.get<LLMProviderListResponse>("/llm-providers/"),
  });

  const deactivate = useMutation({
    mutationFn: (id: string) => api.delete(`/llm-providers/${id}`),
    onSuccess: () => {
      toast.success("Provider deactivated");
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      setDeactivatingId(null);
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to deactivate");
      setDeactivatingId(null);
    },
  });

  const setDefault = useMutation({
    mutationFn: (id: string) =>
      api.post<LLMProviderSetDefaultResponse>(`/llm-providers/${id}/set-default`),
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to set default");
    },
  });

  const providers = data?.providers ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">LLM Providers</h1>
          <p className="text-sm text-slate-400 mt-1">
            Configure AI providers with encrypted API keys and fallback chains
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
            onClick={() => navigate("/llm-providers/new")}
          >
            Add Provider
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="error">
          {error instanceof ApiRequestError ? error.message : "Failed to load providers"}
        </Alert>
      )}

      {/* Empty State */}
      {!isLoading && !error && providers.length === 0 && (
        <Card className="p-12">
          <div className="text-center">
            <div className="mx-auto w-12 h-12 rounded-full bg-slate-700/50 flex items-center justify-center mb-4">
              <Brain className="h-6 w-6 text-slate-500" />
            </div>
            <h3 className="text-sm font-medium text-slate-300 mb-1">
              No LLM providers configured
            </h3>
            <p className="text-xs text-slate-500 mb-4 max-w-sm mx-auto">
              Add your first AI provider to enable natural language queries.
              API keys are encrypted at rest using HKDF.
            </p>
            <Button
              size="sm"
              icon={<Plus className="h-4 w-4" />}
              onClick={() => navigate("/llm-providers/new")}
            >
              Add Provider
            </Button>
          </div>
        </Card>
      )}

      {/* Loading */}
      {isLoading && (
        <Card className="p-12">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
            <span className="text-sm text-slate-400">Loading providers…</span>
          </div>
        </Card>
      )}

      {/* Providers Table */}
      {providers.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/40">
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Provider
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Type
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    SQL Model
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Key
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Priority
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">
                    Residency
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
                {providers.map((prov) => {
                  const res = residencyConfig[prov.data_residency] ?? residencyConfig.unknown;
                  return (
                    <tr
                      key={prov.provider_id}
                      className="hover:bg-slate-800/40 transition-colors"
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2.5">
                          <Brain className="h-4 w-4 text-slate-500 shrink-0" />
                          <span className="text-sm font-medium text-slate-200 truncate max-w-[180px]">
                            {prov.name}
                          </span>
                          {prov.is_default && (
                            <Star className="h-3.5 w-3.5 text-amber-400 fill-amber-400 shrink-0" />
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <ProviderBadge type={prov.provider_type} />
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-sm text-slate-400 font-mono truncate max-w-[160px] block">
                          {prov.model_sql}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-xs text-slate-500 font-mono">
                          {prov.key_prefix ?? "—"}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-sm text-slate-400">{prov.priority}</span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="flex items-center gap-1.5">
                          <Shield className="h-3 w-3 text-slate-600" />
                          <span className={cn("text-xs font-medium", res.color)}>
                            {res.label}
                          </span>
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="flex items-center gap-1.5">
                          <span
                            className={cn(
                              "w-2 h-2 rounded-full shrink-0",
                              prov.is_active ? "bg-emerald-400" : "bg-slate-500"
                            )}
                          />
                          <span className={cn("text-xs", prov.is_active ? "text-emerald-400" : "text-slate-500")}>
                            {prov.is_active ? "Active" : "Inactive"}
                          </span>
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <TestButton providerId={prov.provider_id} />
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center justify-end gap-1">
                          {/* Set Default */}
                          {!prov.is_default && prov.is_active && (
                            <button
                              onClick={() => setDefault.mutate(prov.provider_id)}
                              disabled={setDefault.isPending}
                              className="p-1.5 rounded-md text-slate-400 hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
                              title="Set as default"
                            >
                              <Star className="h-4 w-4" />
                            </button>
                          )}
                          {/* Edit */}
                          <button
                            onClick={() => navigate(`/llm-providers/${prov.provider_id}/edit`)}
                            className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
                            title="Edit"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          {/* Deactivate */}
                          {deactivatingId === prov.provider_id ? (
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => deactivate.mutate(prov.provider_id)}
                                className="text-[11px] px-2 py-1 rounded bg-red-600/80 text-white hover:bg-red-500 transition-colors"
                                disabled={deactivate.isPending}
                              >
                                {deactivate.isPending ? "…" : "Confirm"}
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
                              onClick={() => setDeactivatingId(prov.provider_id)}
                              className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                              title="Deactivate"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {data && (
            <div className="px-6 py-3 border-t border-slate-700/30 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                {data.total} provider{data.total !== 1 ? "s" : ""}
              </span>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
