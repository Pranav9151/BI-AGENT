/**
 * Smart BI Agent — Admin Panel
 * Phase 4E | Admin role only (enforced by backend)
 *
 * User management: list users, create, edit roles, activate/deactivate, approve.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  UserPlus,
  Shield,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  X,
  Key,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Input, Select, Alert } from "@/components/ui";
import type { UserAdmin, UserListResponse, UserCreateRequest } from "@/types/users";

// ─── Role Badges ────────────────────────────────────────────────────────────

const roleConfig: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  admin: {
    label: "Admin",
    icon: <ShieldAlert className="h-3 w-3" />,
    color: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  },
  analyst: {
    label: "Analyst",
    icon: <ShieldCheck className="h-3 w-3" />,
    color: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  },
  viewer: {
    label: "Viewer",
    icon: <Shield className="h-3 w-3" />,
    color: "text-slate-400 bg-slate-500/10 border-slate-500/20",
  },
};

// ─── Create User Modal ──────────────────────────────────────────────────────

const createUserSchema = z.object({
  email: z.string().email("Invalid email"),
  name: z.string().min(1, "Name is required").max(255),
  password: z.string().min(8, "Minimum 8 characters").max(128),
  role: z.enum(["viewer", "analyst", "admin"]),
  department: z.string().max(100).default(""),
});

type CreateUserForm = z.infer<typeof createUserSchema>;

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateUserForm>({
    resolver: zodResolver(createUserSchema),
    defaultValues: {
      email: "",
      name: "",
      password: "",
      role: "viewer",
      department: "",
    },
  });

  const createMutation = useMutation({
    mutationFn: (data: UserCreateRequest) =>
      api.post<UserAdmin>("/users/", data),
    onSuccess: (user) => {
      toast.success(`User "${user.name}" created`);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Failed to create user");
    },
  });

  const onSubmit = (data: CreateUserForm) => {
    createMutation.mutate({
      ...data,
      department: data.department || null,
    } as UserCreateRequest);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-md bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between p-6 border-b border-slate-700/40">
          <h2 className="text-lg font-semibold text-white">Create User</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1">
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          <Input
            label="Email"
            type="email"
            placeholder="user@company.com"
            error={errors.email?.message}
            {...register("email")}
          />
          <Input
            label="Name"
            placeholder="Full name"
            error={errors.name?.message}
            {...register("name")}
          />
          <Input
            label="Password"
            type="password"
            placeholder="Minimum 8 characters"
            autoComplete="new-password"
            error={errors.password?.message}
            {...register("password")}
          />
          <Select
            label="Role"
            options={[
              { value: "viewer", label: "Viewer" },
              { value: "analyst", label: "Analyst" },
              { value: "admin", label: "Admin" },
            ]}
            error={errors.role?.message}
            {...register("role")}
          />
          <Input
            label="Department (optional)"
            placeholder="e.g. Data Analytics"
            error={errors.department?.message}
            {...register("department")}
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" isLoading={createMutation.isPending}>
              Create User
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get<UserListResponse>("/users/?limit=200"),
  });

  // Toggle active
  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.patch(`/users/${id}`, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User status updated");
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  // Toggle approved
  const toggleApproved = useMutation({
    mutationFn: ({ id, is_approved }: { id: string; is_approved: boolean }) =>
      api.patch(`/users/${id}`, { is_approved }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User approval updated");
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  // Change role
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) =>
      api.patch(`/users/${id}`, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("Role updated");
    },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const users = data?.users ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Admin Panel</h1>
          <p className="text-sm text-slate-400 mt-1">User management and system administration</p>
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
            icon={<UserPlus className="h-4 w-4" />}
            onClick={() => setShowCreate(true)}
          >
            Create User
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="error">
          {error instanceof ApiRequestError ? error.message : "Failed to load users"}
        </Alert>
      )}

      {/* Stats */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Card className="p-4 text-center">
            <div className="text-2xl font-bold text-white">{data.meta.total}</div>
            <div className="text-xs text-slate-500 mt-0.5">Total Users</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-2xl font-bold text-emerald-400">
              {users.filter((u) => u.is_active).length}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">Active</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-2xl font-bold text-amber-400">
              {users.filter((u) => !u.is_approved).length}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">Pending Approval</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-2xl font-bold text-blue-400">
              {users.filter((u) => u.totp_enabled).length}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">MFA Enabled</div>
          </Card>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <Card className="p-12">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
            <span className="text-sm text-slate-400">Loading users…</span>
          </div>
        </Card>
      )}

      {/* Users Table */}
      {users.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/40">
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">User</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">Role</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">Department</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">Status</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">MFA</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">Last Login</th>
                  <th className="text-right text-xs font-medium text-slate-500 uppercase tracking-wider px-6 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {users.map((user) => {
                  const rcfg = roleConfig[user.role] ?? roleConfig.viewer;
                  return (
                    <tr key={user.user_id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-6 py-4">
                        <div>
                          <div className="text-sm font-medium text-slate-200">{user.name}</div>
                          <div className="text-xs text-slate-500">{user.email}</div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <select
                          value={user.role}
                          onChange={(e) => changeRole.mutate({ id: user.user_id, role: e.target.value })}
                          className="text-xs bg-transparent border border-slate-700/40 rounded px-2 py-1 text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
                        >
                          <option value="viewer">Viewer</option>
                          <option value="analyst">Analyst</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-sm text-slate-400">{user.department ?? "—"}</span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-col gap-1">
                          <span className="flex items-center gap-1.5">
                            <span className={cn("w-2 h-2 rounded-full", user.is_active ? "bg-emerald-400" : "bg-slate-500")} />
                            <span className={cn("text-xs", user.is_active ? "text-emerald-400" : "text-slate-500")}>
                              {user.is_active ? "Active" : "Inactive"}
                            </span>
                          </span>
                          {!user.is_approved && (
                            <span className="text-[10px] text-amber-400">Pending approval</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {user.totp_enabled ? (
                          <Key className="h-4 w-4 text-emerald-400" />
                        ) : (
                          <span className="text-xs text-slate-600">Off</span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-xs text-slate-500">
                          {user.last_login_at
                            ? new Date(user.last_login_at).toLocaleDateString()
                            : "Never"}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center justify-end gap-1">
                          {/* Approve */}
                          {!user.is_approved && (
                            <button
                              onClick={() => toggleApproved.mutate({ id: user.user_id, is_approved: true })}
                              className="text-[11px] px-2 py-1 rounded bg-emerald-600/80 text-white hover:bg-emerald-500 transition-colors"
                            >
                              Approve
                            </button>
                          )}
                          {/* Toggle active */}
                          <button
                            onClick={() => toggleActive.mutate({ id: user.user_id, is_active: !user.is_active })}
                            className={cn(
                              "p-1.5 rounded-md transition-colors",
                              user.is_active
                                ? "text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                                : "text-slate-400 hover:text-emerald-400 hover:bg-emerald-500/10"
                            )}
                            title={user.is_active ? "Deactivate" : "Activate"}
                          >
                            {user.is_active ? (
                              <XCircle className="h-4 w-4" />
                            ) : (
                              <CheckCircle2 className="h-4 w-4" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Create Modal */}
      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}
