/**
 * Smart BI Agent — Connection Form Page
 * Phase 4A | Admin only
 *
 * Handles both Create (/connections/new) and Edit (/connections/:id/edit).
 * Uses react-hook-form + zod for validation.
 *
 * Security notes:
 *   - Password is never returned by the backend — always empty on edit
 *   - On edit, omitting username/password preserves existing credentials
 *   - SSRF validation happens server-side (not client-side)
 */

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save, Loader2, PlugZap, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { Button, Input, Select, Card, CardHeader, CardContent, Alert } from "@/components/ui";
import type { Connection, ConnectionCreateRequest } from "@/types/connections";

// ─── Constants ──────────────────────────────────────────────────────────────

const DB_TYPE_OPTIONS = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql",      label: "MySQL" },
  { value: "mssql",      label: "SQL Server (MSSQL)" },
  { value: "bigquery",   label: "Google BigQuery" },
  { value: "snowflake",  label: "Snowflake" },
];

const SSL_MODE_OPTIONS = [
  { value: "disable",     label: "Disable" },
  { value: "allow",       label: "Allow" },
  { value: "prefer",      label: "Prefer" },
  { value: "require",     label: "Require (recommended)" },
  { value: "verify-ca",   label: "Verify CA" },
  { value: "verify-full", label: "Verify Full" },
];

const DEFAULT_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql:      3306,
  mssql:      1433,
  bigquery:   443,
  snowflake:  443,
};

// ─── Validation Schema ──────────────────────────────────────────────────────

const connectionSchema = z.object({
  name:           z.string().min(1, "Name is required").max(255),
  db_type:        z.enum(["postgresql", "mysql", "mssql", "bigquery", "snowflake"]),
  host:           z.string().max(500).default(""),
  port:           z.coerce.number().int().min(0).max(65535).default(5432),
  database_name:  z.string().min(1, "Database name / Project ID is required").max(255),
  username:       z.string().max(255).default(""),
  password:       z.string().max(10240).default(""),
  ssl_mode:       z.enum(["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]),
  query_timeout:  z.coerce.number().int().min(1).max(300),
  max_rows:       z.coerce.number().int().min(1).max(100000),
  allowed_schemas: z.string().default("public"),
});

type ConnectionFormData = z.infer<typeof connectionSchema>;

// ─── Page ───────────────────────────────────────────────────────────────────

export default function ConnectionFormPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);

  // Fetch existing connection for edit mode
  const { data: existing, isLoading: loadingExisting } = useQuery({
    queryKey: ["connection", id],
    queryFn: () => api.get<Connection>(`/connections/${id}`),
    enabled: isEdit,
  });

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors, isDirty },
  } = useForm<ConnectionFormData>({
    resolver: zodResolver(connectionSchema),
    defaultValues: {
      name: "",
      db_type: "postgresql",
      host: "",
      port: 5432,
      database_name: "",
      username: "",
      password: "",
      ssl_mode: "require",
      query_timeout: 30,
      max_rows: 10000,
      allowed_schemas: "public",
    },
  });

  const watchDbType = watch("db_type");

  // Populate form when editing
  useEffect(() => {
    if (existing) {
      reset({
        name: existing.name,
        db_type: existing.db_type as ConnectionFormData["db_type"],
        host: existing.host ?? "",
        port: existing.port ?? DEFAULT_PORTS[existing.db_type] ?? 5432,
        database_name: existing.database_name ?? "",
        username: "", // never returned by backend
        password: "", // never returned by backend
        ssl_mode: existing.ssl_mode as ConnectionFormData["ssl_mode"],
        query_timeout: existing.query_timeout,
        max_rows: existing.max_rows,
        allowed_schemas: existing.allowed_schemas?.join(", ") ?? "public",
      });
    }
  }, [existing, reset]);

  // Auto-set port when DB type changes (only on create)
  useEffect(() => {
    if (!isEdit) {
      const newPort = DEFAULT_PORTS[watchDbType];
      if (newPort) {
        setValue("port", newPort);
      }
    }
  }, [watchDbType, isEdit, setValue]);

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (data: ConnectionCreateRequest) =>
      api.post<Connection>("/connections/", data),
    onSuccess: (conn) => {
      toast.success(`Connection "${conn.name}" created`);
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      navigate("/connections");
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to create connection");
    },
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.patch<Connection>(`/connections/${id}`, data),
    onSuccess: (conn) => {
      toast.success(`Connection "${conn.name}" updated`);
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      queryClient.invalidateQueries({ queryKey: ["connection", id] });
      navigate("/connections");
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to update connection");
    },
  });

  const isPending = createMutation.isPending || updateMutation.isPending;

  // ── Test Connection (inline, before saving) ──
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "success" | "failed">("idle");
  const [testError, setTestError] = useState<string | null>(null);

  const handleTestConnection = async () => {
    const data = watch();
    if (data.db_type !== "bigquery" && !data.host.trim()) {
      toast.error("Enter a host before testing"); return;
    }
    if (!data.username) {
      toast.error("Enter credentials before testing"); return;
    }

    setTestStatus("testing");
    setTestError(null);

    try {
      if (isEdit && id && !data.username) {
        // Edit mode with no new credentials — test saved connection
        const result = await api.post<{ success: boolean; error?: string; latency_ms?: number }>(
          `/connections/${id}/test`
        );
        if (result.success) {
          setTestStatus("success");
          toast.success(`Connected successfully (${result.latency_ms}ms)`);
        } else {
          setTestStatus("failed");
          setTestError(result.error || "Connection failed");
          toast.error(result.error || "Connection failed");
        }
      } else {
        // Create mode OR edit with new credentials — test inline without saving
        const schemas = data.allowed_schemas.split(",").map((s) => s.trim()).filter(Boolean);
        const result = await api.post<{ success: boolean; error?: string; latency_ms?: number }>(
          `/connections/test-inline`,
          {
            name: data.name || "test",
            db_type: data.db_type,
            host: data.host,
            port: data.port,
            database_name: data.database_name,
            username: data.username,
            password: data.password,
            ssl_mode: data.ssl_mode,
            query_timeout: data.query_timeout,
            max_rows: data.max_rows,
            allowed_schemas: schemas,
          }
        );
        if (result.success) {
          setTestStatus("success");
          toast.success(`Connected successfully (${result.latency_ms}ms)`);
        } else {
          setTestStatus("failed");
          setTestError(result.error || "Connection failed");
          toast.error(result.error || "Connection failed");
        }
      }
    } catch (err) {
      setTestStatus("failed");
      const msg = err instanceof ApiRequestError ? err.message : "Test failed";
      setTestError(msg);
      toast.error(msg);
    }
  };

  const onSubmit = (data: ConnectionFormData) => {
    // Host is required for non-BigQuery types
    if (data.db_type !== "bigquery" && !data.host.trim()) {
      toast.error("Host is required for this database type");
      return;
    }

    const schemas = data.allowed_schemas
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    if (isEdit) {
      // Build partial update — only send changed fields
      // Always omit credentials if both are empty (preserves existing)
      const update: Record<string, unknown> = {
        name: data.name,
        host: data.host,
        port: data.port,
        database_name: data.database_name,
        ssl_mode: data.ssl_mode,
        query_timeout: data.query_timeout,
        max_rows: data.max_rows,
        allowed_schemas: schemas,
      };

      // Only send credentials if the user explicitly entered them
      if (data.username) update.username = data.username;
      if (data.password) update.password = data.password;

      updateMutation.mutate(update);
    } else {
      // Create requires all fields including credentials
      if (!data.username) {
        toast.error("Username is required for new connections");
        return;
      }

      createMutation.mutate({
        ...data,
        allowed_schemas: schemas,
      } as ConnectionCreateRequest);
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
          onClick={() => navigate("/connections")}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-white">
            {isEdit ? "Edit Connection" : "New Connection"}
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {isEdit
              ? "Update connection settings. Leave credentials empty to keep existing."
              : "Credentials are encrypted at rest using HKDF."}
          </p>
        </div>
      </div>

      {/* Mutation errors */}
      {(createMutation.error || updateMutation.error) && (
        <Alert variant="error">
          {(createMutation.error as ApiRequestError)?.message ??
            (updateMutation.error as ApiRequestError)?.message ??
            "An error occurred"}
        </Alert>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit(onSubmit)}>
        {/* General */}
        <Card className="mb-4">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">General</h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <Input
              label="Connection Name"
              placeholder="e.g. Production Data Warehouse"
              error={errors.name?.message}
              {...register("name")}
            />
            <Select
              label="Database Type"
              options={DB_TYPE_OPTIONS}
              error={errors.db_type?.message}
              {...register("db_type")}
            />
          </CardContent>
        </Card>

        {/* Connection Details */}
        <Card className="mb-4">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">
              Connection Details
            </h2>
          </CardHeader>
          <CardContent className="space-y-4">
            {watchDbType !== "bigquery" ? (
              <>
                <div className="grid grid-cols-3 gap-4">
                  <div className="col-span-2">
                    <Input
                      label="Host"
                      placeholder="e.g. db.example.com"
                      error={errors.host?.message}
                      {...register("host")}
                    />
                  </div>
                  <Input
                    label="Port"
                    type="number"
                    error={errors.port?.message}
                    {...register("port")}
                  />
                </div>
                <Input
                  label="Database Name"
                  placeholder="e.g. analytics_db"
                  error={errors.database_name?.message}
                  {...register("database_name")}
                />
                <Select
                  label="SSL Mode"
                  options={SSL_MODE_OPTIONS}
                  error={errors.ssl_mode?.message}
                  {...register("ssl_mode")}
                />
              </>
            ) : (
              <>
                <Input
                  label="GCP Project ID"
                  placeholder="e.g. my-gcp-project-123"
                  hint="The Google Cloud project containing your BigQuery datasets"
                  error={errors.database_name?.message}
                  {...register("database_name")}
                />
                <Input
                  label="Default Dataset"
                  placeholder="e.g. analytics"
                  hint="Comma-separated. Tables will be read from these datasets."
                  error={errors.allowed_schemas?.message}
                  {...register("allowed_schemas")}
                />
              </>
            )}
          </CardContent>
        </Card>

        {/* Credentials */}
        <Card className="mb-4">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">
              Credentials
            </h2>
            {isEdit && (
              <p className="text-xs text-slate-500 mt-0.5">
                Leave both fields empty to keep existing credentials unchanged.
              </p>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            <Input
              label={watchDbType === "bigquery" ? "Service Account Email" : "Username"}
              placeholder={isEdit ? "(unchanged)" : watchDbType === "bigquery" ? "sa@project.iam.gserviceaccount.com" : "Database username"}
              autoComplete="off"
              error={errors.username?.message}
              {...register("username")}
            />
            <Input
              label={watchDbType === "bigquery" ? "Service Account JSON Key" : "Password"}
              type={watchDbType === "bigquery" ? "text" : "password"}
              placeholder={isEdit ? "(unchanged)" : watchDbType === "bigquery" ? "Paste full JSON key…" : "Database password"}
              autoComplete="new-password"
              error={errors.password?.message}
              {...register("password")}
            />
            {watchDbType === "bigquery" && (
              <p className="text-[10px] text-slate-500">
                Paste the full service account JSON key. It will be encrypted at rest using HKDF.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Query Settings */}
        <Card className="mb-6">
          <CardHeader>
            <h2 className="text-sm font-semibold text-slate-200">
              Query Settings
            </h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Query Timeout (seconds)"
                type="number"
                hint="1–300 seconds"
                error={errors.query_timeout?.message}
                {...register("query_timeout")}
              />
              <Input
                label="Max Rows"
                type="number"
                hint="1–100,000 rows"
                error={errors.max_rows?.message}
                {...register("max_rows")}
              />
            </div>
            {watchDbType !== "bigquery" && (
              <Input
                label="Allowed Schemas"
                placeholder="public, analytics"
                hint="Comma-separated list of schemas accessible through this connection"
                error={errors.allowed_schemas?.message}
                {...register("allowed_schemas")}
              />
            )}
          </CardContent>
        </Card>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="ghost"
            onClick={() => navigate("/connections")}
          >
            Cancel
          </Button>
          <div className="flex items-center gap-3">
            {/* Test Connection Button */}
            <Button
              type="button"
              variant="ghost"
              icon={
                testStatus === "testing" ? <Loader2 className="h-4 w-4 animate-spin" /> :
                testStatus === "success" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> :
                testStatus === "failed" ? <XCircle className="h-4 w-4 text-red-400" /> :
                <PlugZap className="h-4 w-4" />
              }
              onClick={handleTestConnection}
              disabled={testStatus === "testing"}
            >
              {testStatus === "success" ? "Connected" : testStatus === "failed" ? "Failed" : "Test Connection"}
            </Button>
            {testError && (
              <span className="text-xs text-red-400 max-w-[200px] truncate" title={testError}>
                {testError}
              </span>
            )}
            <Button
              type="submit"
              icon={<Save className="h-4 w-4" />}
              isLoading={isPending}
              disabled={isEdit && !isDirty}
            >
              {isEdit ? "Save Changes" : "Create Connection"}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}