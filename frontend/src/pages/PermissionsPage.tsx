/**
 * Smart BI Agent — Permissions Page
 * Phase 6 | Session 7 | Admin only
 *
 * 3-tier RBAC management: Role → Department → User Override
 * Per-connection table/column access control with visual matrix.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Shield, Plus, Trash2, RefreshCw, Loader2, X,
  Users, Building2, User, Database, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input, Select } from "@/components/ui";
import type { ConnectionListResponse } from "@/types/connections";
import type {
  RolePermission, RolePermissionListResponse,
  DepartmentPermission, DepartmentPermissionListResponse,
  UserPermission, UserPermissionListResponse,
} from "@/types/permissions";

type PermTab = "roles" | "departments" | "users";

const TAB_CONFIG: Record<PermTab, { label: string; icon: React.ReactNode }> = {
  roles: { label: "Role Permissions", icon: <Users className="h-3.5 w-3.5" /> },
  departments: { label: "Department", icon: <Building2 className="h-3.5 w-3.5" /> },
  users: { label: "User Override", icon: <User className="h-3.5 w-3.5" /> },
};

function AddPermissionModal({
  tier, connectionId, onClose, onCreated,
}: { tier: PermTab; connectionId: string; onClose: () => void; onCreated: () => void }) {
  const [identifier, setIdentifier] = useState("");
  const [allowedTables, setAllowedTables] = useState("");
  const [deniedColumns, setDeniedColumns] = useState("");
  const [deniedTables, setDeniedTables] = useState("");

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => {
      const path = tier === "roles" ? "/permissions/roles/" : tier === "departments" ? "/permissions/departments/" : "/permissions/users/";
      return api.post(path, body);
    },
    onSuccess: () => { toast.success("Permission created"); onCreated(); onClose(); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const handleCreate = () => {
    if (!identifier.trim()) { toast.error(tier === "roles" ? "Role is required" : tier === "departments" ? "Department is required" : "User ID is required"); return; }
    const tables = allowedTables.split(",").map((t) => t.trim()).filter(Boolean);
    const cols = deniedColumns.split(",").map((c) => c.trim()).filter(Boolean);

    const body: Record<string, unknown> = { connection_id: connectionId };
    if (tier === "roles") { body.role = identifier.trim(); body.allowed_tables = tables; body.denied_columns = cols; }
    else if (tier === "departments") { body.department = identifier.trim(); body.allowed_tables = tables; body.denied_columns = cols; }
    else {
      body.user_id = identifier.trim();
      body.allowed_tables = tables;
      body.denied_tables = deniedTables.split(",").map((t) => t.trim()).filter(Boolean);
      body.denied_columns = cols;
    }
    createMutation.mutate(body);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md glass-strong rounded-2xl shadow-2xl animate-page-in">
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <h2 className="text-base font-semibold text-white">Add {TAB_CONFIG[tier].label}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          {tier === "roles" ? (
            <Select label="Role" value={identifier} onChange={(e) => setIdentifier(e.target.value)}
              options={[{ value: "viewer", label: "Viewer" }, { value: "analyst", label: "Analyst" }, { value: "admin", label: "Admin" }]} />
          ) : tier === "departments" ? (
            <Input label="Department Name" placeholder="e.g. Finance" value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
          ) : (
            <Input label="User ID (UUID)" placeholder="UUID of the user" value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
          )}
          <Input label="Allowed Tables" placeholder="Comma-separated, e.g. orders, customers" value={allowedTables} onChange={(e) => setAllowedTables(e.target.value)}
            hint="Leave empty for all tables" />
          <Input label="Denied Columns" placeholder="Comma-separated, e.g. salary, ssn" value={deniedColumns} onChange={(e) => setDeniedColumns(e.target.value)} />
          {tier === "users" && <Input label="Denied Tables" placeholder="Comma-separated tables to block" value={deniedTables} onChange={(e) => setDeniedTables(e.target.value)} />}
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleCreate} isLoading={createMutation.isPending}>Create</Button>
        </div>
      </div>
    </div>
  );
}

function PermissionCard({ perm, tier, onDelete }: { perm: Record<string, unknown>; tier: PermTab; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const id = (perm.permission_id as string) || "";
  const label = tier === "roles" ? (perm.role as string) : tier === "departments" ? (perm.department as string) : (perm.user_id as string)?.slice(0, 8) + "…";
  const allowed = (perm.allowed_tables as string[]) || [];
  const deniedCols = (perm.denied_columns as string[]) || [];
  const deniedTbls = (perm.denied_tables as string[]) || [];

  return (
    <Card className="p-3">
      <div className="flex items-center justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {TAB_CONFIG[tier].icon}
            <span className="text-sm font-medium text-slate-200">{label}</span>
          </div>
          <div className="flex flex-wrap gap-2 mt-2 text-[10px] text-slate-500">
            {allowed.length > 0 && <span className="text-emerald-400">Allow: {allowed.join(", ")}</span>}
            {allowed.length === 0 && <span className="text-slate-600">All tables</span>}
            {deniedCols.length > 0 && <span className="text-red-400">Deny cols: {deniedCols.join(", ")}</span>}
            {deniedTbls.length > 0 && <span className="text-red-400">Deny tables: {deniedTbls.join(", ")}</span>}
          </div>
        </div>
        {confirming ? (
          <div className="flex items-center gap-1">
            <button onClick={onDelete} className="text-[10px] px-1.5 py-0.5 rounded bg-red-600/80 text-white hover:bg-red-500">Delete</button>
            <button onClick={() => setConfirming(false)} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">No</button>
          </div>
        ) : (
          <button onClick={() => setConfirming(true)} className="p-1.5 rounded text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"><Trash2 className="h-3.5 w-3.5" /></button>
        )}
      </div>
    </Card>
  );
}

export default function PermissionsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<PermTab>("roles");
  const [selectedConnection, setSelectedConnection] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  const { data: connData } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionListResponse>("/connections/"),
  });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];
  if (connections.length > 0 && !selectedConnection) setSelectedConnection(connections[0].connection_id);

  const { data: roleData, isLoading: rolesLoading } = useQuery({
    queryKey: ["permissions", "roles", selectedConnection],
    queryFn: () => api.get<RolePermissionListResponse>(`/permissions/roles/?connection_id=${selectedConnection}`),
    enabled: !!selectedConnection && activeTab === "roles",
  });

  const { data: deptData, isLoading: deptsLoading } = useQuery({
    queryKey: ["permissions", "departments", selectedConnection],
    queryFn: () => api.get<DepartmentPermissionListResponse>(`/permissions/departments/?connection_id=${selectedConnection}`),
    enabled: !!selectedConnection && activeTab === "departments",
  });

  const { data: userData, isLoading: usersLoading } = useQuery({
    queryKey: ["permissions", "users", selectedConnection],
    queryFn: () => api.get<UserPermissionListResponse>(`/permissions/users/?connection_id=${selectedConnection}`),
    enabled: !!selectedConnection && activeTab === "users",
  });

  const deleteMutation = useMutation({
    mutationFn: ({ tier, id }: { tier: PermTab; id: string }) => {
      const path = tier === "roles" ? `/permissions/roles/${id}` : tier === "departments" ? `/permissions/departments/${id}` : `/permissions/users/${id}`;
      return api.delete(path);
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["permissions"] }); toast.success("Permission deleted"); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const isLoading = activeTab === "roles" ? rolesLoading : activeTab === "departments" ? deptsLoading : usersLoading;
  const perms: Record<string, unknown>[] = activeTab === "roles" ? (roleData?.permissions ?? []) : activeTab === "departments" ? (deptData?.permissions ?? []) : (userData?.permissions ?? []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <span className="p-2 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 border border-amber-500/15">
              <Shield className="h-5 w-5 text-amber-400" />
            </span>
            Permissions
          </h1>
          <p className="text-sm text-slate-400 mt-1">3-tier RBAC: Role → Department → User override</p>
        </div>
        {selectedConnection && <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setShowAdd(true)}>Add Permission</Button>}
      </div>

      <div className="flex items-center gap-3">
        <Database className="h-4 w-4 text-slate-500 shrink-0" />
        <select value={selectedConnection} onChange={(e) => setSelectedConnection(e.target.value)}
          className="flex-1 h-9 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-300 text-sm px-3 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500/40">
          <option value="" disabled>Select connection…</option>
          {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name} ({c.db_type})</option>)}
        </select>
      </div>

      <div className="flex border-b border-slate-700/40">
        {(Object.entries(TAB_CONFIG) as [PermTab, { label: string; icon: React.ReactNode }][]).map(([key, cfg]) => (
          <button key={key} onClick={() => setActiveTab(key)}
            className={cn("flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 -mb-px transition-all",
              activeTab === key ? "border-blue-500 text-blue-400" : "border-transparent text-slate-500 hover:text-slate-300")}>
            {cfg.icon}{cfg.label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1,2,3].map((i) => (
            <Card key={i} className="p-3"><div className="animate-skeleton rounded h-14 bg-slate-700/30" /></Card>
          ))}
        </div>
      )}

      {!isLoading && perms.length === 0 && (
        <Card className="p-8">
          <div className="text-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-500/10 to-orange-500/5 border border-amber-500/10 flex items-center justify-center mx-auto mb-3">
              <Shield className="h-6 w-6 text-slate-600" />
            </div>
            <p className="text-sm font-medium text-slate-300">No {activeTab} permissions for this connection</p>
            <p className="text-xs text-slate-500 mt-1">Add permissions to control table and column access.</p>
          </div>
        </Card>
      )}

      {perms.length > 0 && (
        <div className="space-y-2">
          {perms.map((p) => (
            <PermissionCard key={p.permission_id as string} perm={p} tier={activeTab}
              onDelete={() => deleteMutation.mutate({ tier: activeTab, id: p.permission_id as string })} />
          ))}
        </div>
      )}

      {showAdd && selectedConnection && (
        <AddPermissionModal tier={activeTab} connectionId={selectedConnection}
          onClose={() => setShowAdd(false)} onCreated={() => queryClient.invalidateQueries({ queryKey: ["permissions"] })} />
      )}
    </div>
  );
}
