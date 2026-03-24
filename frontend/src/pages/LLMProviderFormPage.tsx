/**
 * Smart BI Agent — LLM Provider Form Page
 * Phase 4B | Admin only
 *
 * Handles both Create (/llm-providers/new) and Edit (/llm-providers/:id/edit).
 * Uses react-hook-form + zod for validation.
 *
 * Security notes:
 *   - API key is never returned by the backend — always empty on edit
 *   - On edit, omitting api_key preserves existing encrypted key
 *   - Ollama does not require an API key (self-hosted)
 */

import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { Button, Input, Select, Card, CardHeader, CardContent, Alert } from "@/components/ui";
import type { LLMProvider, LLMProviderCreateRequest } from "@/types/llm-providers";

// ─── Constants ──────────────────────────────────────────────────────────────

const PROVIDER_TYPE_OPTIONS = [
  { value: "openai",   label: "OpenAI" },
  { value: "claude",   label: "Claude (Anthropic)" },
  { value: "gemini",   label: "Gemini (Google)" },
  { value: "groq",     label: "Groq" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "ollama",   label: "Ollama (Self-hosted)" },
];

const DATA_RESIDENCY_OPTIONS = [
  { value: "us",      label: "United States" },
  { value: "eu",      label: "European Union" },
  { value: "cn",      label: "China" },
  { value: "local",   label: "Local / On-premise" },
  { value: "unknown", label: "Unknown" },
];

/** Default SQL models per provider — matches backend _PROVIDER_MODELS registry */
const DEFAULT_MODELS: Record<string, { sql: string; insight: string }> = {
  openai:   { sql: "gpt-4o",                   insight: "gpt-4o-mini" },
  claude:   { sql: "claude-sonnet-4-6",     insight: "claude-haiku-4-5-20251001" },
  gemini:   { sql: "gemini-2.0-flash",         insight: "gemini-1.5-flash" },
  groq:     { sql: "llama-3.3-70b-versatile",  insight: "llama-3.1-8b-instant" },
  deepseek: { sql: "deepseek-chat",            insight: "deepseek-chat" },
  ollama:   { sql: "llama3.3:70b",             insight: "llama3.2:3b" },
};

// ─── Validation Schema ──────────────────────────────────────────────────────

const providerSchema = z.object({
  name:                z.string().min(1, "Name is required").max(100),
  provider_type:       z.enum(["openai", "claude", "gemini", "groq", "deepseek", "ollama"]),
  api_key:             z.string().max(512).default(""),
  base_url:            z.string().max(500).default(""),
  model_sql:           z.string().min(1, "SQL model is required").max(100),
  model_insight:       z.string().max(100).default(""),
  model_suggestion:    z.string().max(100).default(""),
  max_tokens_sql:      z.coerce.number().int().min(256).max(16384),
  max_tokens_insight:  z.coerce.number().int().min(128).max(8192),
  temperature_sql:     z.coerce.number().min(0).max(1),
  temperature_insight: z.coerce.number().min(0).max(1),
  is_active:           z.boolean(),
  is_default:          z.boolean(),
  priority:            z.coerce.number().int().min(1).max(999),
  daily_token_budget:  z.coerce.number().int().min(1000),
  data_residency:      z.enum(["us", "eu", "cn", "local", "unknown"]),
});

type ProviderFormData = z.infer<typeof providerSchema>;

// ─── Page ───────────────────────────────────────────────────────────────────

export default function LLMProviderFormPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);

  const { data: existing, isLoading: loadingExisting } = useQuery({
    queryKey: ["llm-provider", id],
    queryFn: () => api.get<LLMProvider>(`/llm-providers/${id}`),
    enabled: isEdit,
  });

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors, isDirty },
  } = useForm<ProviderFormData>({
    resolver: zodResolver(providerSchema),
    defaultValues: {
      name: "",
      provider_type: "groq",
      api_key: "",
      base_url: "",
      model_sql: "llama-3.3-70b-versatile",
      model_insight: "llama-3.1-8b-instant",
      model_suggestion: "",
      max_tokens_sql: 2048,
      max_tokens_insight: 1024,
      temperature_sql: 0.1,
      temperature_insight: 0.3,
      is_active: true,
      is_default: false,
      priority: 99,
      daily_token_budget: 1000000,
      data_residency: "unknown",
    },
  });

  const watchProviderType = watch("provider_type");
  const isOllama = watchProviderType === "ollama";

  // Populate form when editing
  useEffect(() => {
    if (existing) {
      reset({
        name: existing.name,
        provider_type: existing.provider_type as ProviderFormData["provider_type"],
        api_key: "", // never returned by backend
        base_url: existing.base_url ?? "",
        model_sql: existing.model_sql,
        model_insight: existing.model_insight ?? "",
        model_suggestion: existing.model_suggestion ?? "",
        max_tokens_sql: existing.max_tokens_sql,
        max_tokens_insight: existing.max_tokens_insight,
        temperature_sql: existing.temperature_sql,
        temperature_insight: existing.temperature_insight,
        is_active: existing.is_active,
        is_default: existing.is_default,
        priority: existing.priority,
        daily_token_budget: existing.daily_token_budget,
        data_residency: existing.data_residency as ProviderFormData["data_residency"],
      });
    }
  }, [existing, reset]);

  // Auto-set models when provider type changes (only on create)
  useEffect(() => {
    if (!isEdit) {
      const defaults = DEFAULT_MODELS[watchProviderType];
      if (defaults) {
        setValue("model_sql", defaults.sql);
        setValue("model_insight", defaults.insight);
      }
      // Auto-set residency for Ollama
      if (watchProviderType === "ollama") {
        setValue("data_residency", "local");
      }
    }
  }, [watchProviderType, isEdit, setValue]);

  // Create
  const createMutation = useMutation({
    mutationFn: (data: LLMProviderCreateRequest) =>
      api.post<LLMProvider>("/llm-providers/", data),
    onSuccess: (prov) => {
      toast.success(`Provider "${prov.name}" created`);
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      navigate("/llm-providers");
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to create provider");
    },
  });

  // Update
  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.patch<LLMProvider>(`/llm-providers/${id}`, data),
    onSuccess: (prov) => {
      toast.success(`Provider "${prov.name}" updated`);
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      queryClient.invalidateQueries({ queryKey: ["llm-provider", id] });
      navigate("/llm-providers");
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to update provider");
    },
  });

  const isPending = createMutation.isPending || updateMutation.isPending;

  const onSubmit = (data: ProviderFormData) => {
    if (isEdit) {
      const update: Record<string, unknown> = {
        name: data.name,
        model_sql: data.model_sql,
        model_insight: data.model_insight || null,
        model_suggestion: data.model_suggestion || null,
        max_tokens_sql: data.max_tokens_sql,
        max_tokens_insight: data.max_tokens_insight,
        temperature_sql: data.temperature_sql,
        temperature_insight: data.temperature_insight,
        is_active: data.is_active,
        is_default: data.is_default,
        priority: data.priority,
        daily_token_budget: data.daily_token_budget,
        data_residency: data.data_residency,
      };
      if (data.api_key) update.api_key = data.api_key;
      if (data.base_url) update.base_url = data.base_url;

      updateMutation.mutate(update);
    } else {
      // Validate: cloud providers need an API key
      if (!isOllama && !data.api_key) {
        toast.error("API key is required for cloud providers");
        return;
      }

      createMutation.mutate({
        ...data,
        api_key: data.api_key || null,
        base_url: data.base_url || null,
        model_insight: data.model_insight || null,
        model_suggestion: data.model_suggestion || null,
      } as LLMProviderCreateRequest);
    }
  };

  if (isEdit && loadingExisting) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 text-blue-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate("/llm-providers")}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-white">
            {isEdit ? "Edit Provider" : "New LLM Provider"}
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {isEdit
              ? "Update provider settings. Leave API key empty to keep existing."
              : "API keys are encrypted at rest using HKDF."}
          </p>
        </div>
      </div>

      {(createMutation.error || updateMutation.error) && (
        <Alert variant="error">
          {(createMutation.error as ApiRequestError)?.message ??
            (updateMutation.error as ApiRequestError)?.message ??
            "An error occurred"}
        </Alert>
      )}

      <form onSubmit={handleSubmit(onSubmit)}>
        {/* General */}
        <Card className="mb-4">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">General</h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <Input
              label="Provider Name"
              placeholder="e.g. Company Groq Account"
              error={errors.name?.message}
              {...register("name")}
            />
            <Select
              label="Provider Type"
              options={PROVIDER_TYPE_OPTIONS}
              error={errors.provider_type?.message}
              disabled={isEdit}
              {...register("provider_type")}
            />
          </CardContent>
        </Card>

        {/* Credentials */}
        <Card className="mb-4">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">Credentials</h2>
            {isEdit && (
              <p className="text-xs text-slate-500 mt-0.5">
                Leave API key empty to keep existing key unchanged.
              </p>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {!isOllama && (
              <Input
                label="API Key"
                type="password"
                placeholder={isEdit ? "(unchanged)" : "Enter API key"}
                autoComplete="new-password"
                error={errors.api_key?.message}
                {...register("api_key")}
              />
            )}
            {isOllama && (
              <Input
                label="Base URL"
                placeholder="http://ollama:11434"
                hint="SSRF-validated. Must be Docker-internal network for security."
                error={errors.base_url?.message}
                {...register("base_url")}
              />
            )}
          </CardContent>
        </Card>

        {/* Models */}
        <Card className="mb-4">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">Model Configuration</h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <Input
              label="SQL Model"
              placeholder="Model for SQL generation"
              hint="Accuracy-critical — use a strong model"
              error={errors.model_sql?.message}
              {...register("model_sql")}
            />
            <Input
              label="Insight Model"
              placeholder="Model for result summarisation"
              hint="Can be lighter/cheaper than SQL model"
              error={errors.model_insight?.message}
              {...register("model_insight")}
            />
            <Input
              label="Suggestion Model (optional)"
              placeholder="Model for question suggestions"
              error={errors.model_suggestion?.message}
              {...register("model_suggestion")}
            />
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="SQL Max Tokens"
                type="number"
                error={errors.max_tokens_sql?.message}
                {...register("max_tokens_sql")}
              />
              <Input
                label="Insight Max Tokens"
                type="number"
                error={errors.max_tokens_insight?.message}
                {...register("max_tokens_insight")}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="SQL Temperature"
                type="number"
                step="0.05"
                hint="0.0 (deterministic) – 1.0 (creative)"
                error={errors.temperature_sql?.message}
                {...register("temperature_sql")}
              />
              <Input
                label="Insight Temperature"
                type="number"
                step="0.05"
                error={errors.temperature_insight?.message}
                {...register("temperature_insight")}
              />
            </div>
          </CardContent>
        </Card>

        {/* Operational */}
        <Card className="mb-6">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">Operational Settings</h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Priority"
                type="number"
                hint="1 = primary, higher = lower priority in fallback chain"
                error={errors.priority?.message}
                {...register("priority")}
              />
              <Input
                label="Daily Token Budget"
                type="number"
                hint="Per-provider daily limit"
                error={errors.daily_token_budget?.message}
                {...register("daily_token_budget")}
              />
            </div>
            <Select
              label="Data Residency"
              options={DATA_RESIDENCY_OPTIONS}
              error={errors.data_residency?.message}
              {...register("data_residency")}
            />
            <div className="grid grid-cols-2 gap-4">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded border-slate-600 bg-slate-800/60 text-blue-500 focus:ring-blue-500/40 focus:ring-offset-slate-900"
                  {...register("is_active")}
                />
                <span className="text-sm text-slate-300">Active</span>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded border-slate-600 bg-slate-800/60 text-blue-500 focus:ring-blue-500/40 focus:ring-offset-slate-900"
                  {...register("is_default")}
                />
                <span className="text-sm text-slate-300">Set as Default</span>
              </label>
            </div>
          </CardContent>
        </Card>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="ghost"
            onClick={() => navigate("/llm-providers")}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            icon={<Save className="h-4 w-4" />}
            isLoading={isPending}
            disabled={isEdit && !isDirty}
          >
            {isEdit ? "Save Changes" : "Create Provider"}
          </Button>
        </div>
      </form>
    </div>
  );
}
