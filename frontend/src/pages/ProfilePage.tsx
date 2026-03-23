import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  User as UserIcon,
  Mail,
  Shield,
  Building2,
  Clock,
  CheckCircle2,
  ShieldCheck,
  ShieldOff,
} from "lucide-react";

import { useAuthStore } from "@/stores/auth-store";
import { Button, Input, Card, CardHeader, CardContent, Alert } from "@/components/ui";

// ─── Validation ──────────────────────────────────────────────────────────────

const profileSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  department: z.string().max(100).optional().or(z.literal("")),
});

type ProfileFormData = z.infer<typeof profileSchema>;

// ─── Component ───────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const { user, updateProfile, isLoading, error, clearError } = useAuthStore();
  const [saved, setSaved] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors: formErrors, isDirty },
  } = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      name: user?.name ?? "",
      department: user?.department ?? "",
    },
  });

  if (!user) return null;

  const onSubmit = async (data: ProfileFormData) => {
    clearError();
    setSaved(false);
    try {
      await updateProfile({
        name: data.name,
        department: data.department || null,
      });
      setSaved(true);
      toast.success("Profile updated");
      setTimeout(() => setSaved(false), 3000);
    } catch {
      toast.error("Failed to update profile");
    }
  };

  const roleBadge = {
    admin: { label: "Administrator", color: "bg-amber-500/15 text-amber-300 border-amber-500/20" },
    analyst: { label: "Analyst", color: "bg-blue-500/15 text-blue-300 border-blue-500/20" },
    viewer: { label: "Viewer", color: "bg-slate-500/15 text-slate-300 border-slate-500/20" },
  }[user.role];

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Profile</h1>
        <p className="text-sm text-slate-400 mt-1">
          View and manage your account settings
        </p>
      </div>

      {/* Account Info Card */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-white">
            Account information
          </h2>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <InfoField
              icon={<Mail className="h-4 w-4" />}
              label="Email"
              value={user.email}
            />
            <InfoField
              icon={<Shield className="h-4 w-4" />}
              label="Role"
              value={
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${roleBadge.color}`}
                >
                  {roleBadge.label}
                </span>
              }
            />
            <InfoField
              icon={<Clock className="h-4 w-4" />}
              label="Last login"
              value={
                user.last_login_at
                  ? new Date(user.last_login_at).toLocaleString()
                  : "Never"
              }
            />
            <InfoField
              icon={
                user.totp_enabled ? (
                  <ShieldCheck className="h-4 w-4" />
                ) : (
                  <ShieldOff className="h-4 w-4" />
                )
              }
              label="Two-factor auth"
              value={
                <span
                  className={
                    user.totp_enabled ? "text-emerald-400" : "text-slate-500"
                  }
                >
                  {user.totp_enabled ? "Enabled" : "Not enabled"}
                </span>
              }
            />
          </div>
        </CardContent>
      </Card>

      {/* Edit Profile Card */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-white">
            Edit profile
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            You can update your name and department
          </p>
        </CardHeader>
        <CardContent>
          {error && (
            <Alert variant="error" className="mb-4" onDismiss={clearError}>
              {error}
            </Alert>
          )}
          {saved && (
            <Alert variant="success" className="mb-4">
              Profile saved successfully
            </Alert>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <Input
              label="Name"
              placeholder="Your display name"
              icon={<UserIcon className="h-4 w-4" />}
              error={formErrors.name?.message}
              {...register("name")}
            />

            <Input
              label="Department"
              placeholder="e.g. Engineering, Finance"
              icon={<Building2 className="h-4 w-4" />}
              error={formErrors.department?.message}
              hint="Optional — used for department-level permissions"
              {...register("department")}
            />

            <div className="flex justify-end pt-2">
              <Button
                type="submit"
                isLoading={isLoading}
                disabled={!isDirty}
                icon={<CheckCircle2 className="h-4 w-4" />}
              >
                Save changes
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Helper ──────────────────────────────────────────────────────────────────

function InfoField({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <div className="mt-0.5 text-slate-500">{icon}</div>
      <div>
        <p className="text-xs text-slate-500 mb-0.5">{label}</p>
        <div className="text-sm text-slate-200">{value}</div>
      </div>
    </div>
  );
}
