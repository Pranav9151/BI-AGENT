/**
 * Smart BI Agent — Register Page (Phase 11)
 * Self-service registration with company domain restriction.
 * Admin approves before user can login.
 */
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Mail, Lock, User, Building2, ArrowLeft, Check } from "lucide-react";

import { api, ApiRequestError } from "@/lib/api";
import { AuthLayout } from "@/components/auth";
import { Button, Input, Card, CardHeader, CardContent, Alert } from "@/components/ui";

const registerSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters").max(100),
  email: z.string().min(1, "Email is required").email("Please enter a valid email"),
  password: z.string().min(8, "Password must be at least 8 characters").max(128),
  department: z.string().max(100).optional(),
});

type RegisterForm = z.infer<typeof registerSchema>;

export default function RegisterPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema),
    defaultValues: { name: "", email: "", password: "", department: "" },
  });

  const password = watch("password", "");
  const strength = (() => {
    let s = 0;
    if (password.length >= 8) s++;
    if (password.length >= 12) s++;
    if (/[A-Z]/.test(password)) s++;
    if (/[0-9]/.test(password)) s++;
    if (/[^A-Za-z0-9]/.test(password)) s++;
    return s;
  })();
  const strengthLabel = ["", "Weak", "Fair", "Good", "Strong", "Excellent"][strength];
  const strengthColor = ["", "bg-red-500", "bg-amber-500", "bg-yellow-500", "bg-emerald-500", "bg-emerald-400"][strength];

  const onSubmit = async (data: RegisterForm) => {
    setError(null);
    setLoading(true);
    try {
      await api.post("/auth/register", {
        email: data.email,
        name: data.name,
        password: data.password,
        department: data.department || null,
      });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof ApiRequestError
        ? (err.fields?.length
            ? err.fields.map((f: { field: string; issue: string }) => `${f.field.replace('body → ', '')}: ${f.issue}`).join('. ')
            : err.message)
        : "Registration failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <AuthLayout>
        <Card className="w-full max-w-sm">
          <CardContent>
            <div className="text-center py-6">
              <div className="w-14 h-14 rounded-full bg-emerald-500/15 border border-emerald-500/20 flex items-center justify-center mx-auto mb-4">
                <Check className="h-7 w-7 text-emerald-400" />
              </div>
              <h2 className="text-lg font-semibold text-white mb-2">Registration Submitted</h2>
              <p className="text-sm text-slate-400 leading-relaxed mb-6">
                Your account has been created. An administrator will review and approve your access.
                You&apos;ll be able to sign in once approved.
              </p>
              <Button onClick={() => navigate("/login")} className="w-full">
                Back to Sign In
              </Button>
            </div>
          </CardContent>
        </Card>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white">Create Account</h2>
          <p className="text-sm text-slate-400 mt-1">
            Use your company email to register
          </p>
        </CardHeader>

        <CardContent>
          {error && (
            <Alert variant="error" className="mb-5" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <Input
              label="Full Name"
              placeholder="Your full name"
              autoComplete="name"
              autoFocus
              icon={<User className="h-4 w-4" />}
              error={errors.name?.message}
              {...register("name")}
            />

            <Input
              label="Company Email"
              type="email"
              placeholder="you@company.com"
              autoComplete="email"
              icon={<Mail className="h-4 w-4" />}
              error={errors.email?.message}
              {...register("email")}
            />

            <div>
              <Input
                label="Password"
                type="password"
                placeholder="Min. 8 characters"
                autoComplete="new-password"
                icon={<Lock className="h-4 w-4" />}
                error={errors.password?.message}
                {...register("password")}
              />
              {password.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${i <= strength ? strengthColor : "bg-slate-700/40"}`} />
                    ))}
                  </div>
                  <p className={`text-[10px] ${strength >= 4 ? "text-emerald-400" : strength >= 2 ? "text-amber-400" : "text-red-400"}`}>
                    {strengthLabel}
                  </p>
                </div>
              )}
            </div>

            <Input
              label="Department (Optional)"
              placeholder="e.g. Finance, HR, Operations"
              icon={<Building2 className="h-4 w-4" />}
              error={errors.department?.message}
              {...register("department")}
            />

            <Button
              type="submit"
              className="w-full mt-2"
              size="lg"
              isLoading={loading}
            >
              Create Account
            </Button>
          </form>

          <div className="mt-5 pt-4 border-t border-slate-700/40">
            <p className="text-xs text-slate-500 text-center">
              Already have an account?{" "}
              <Link to="/login" className="text-blue-400 hover:text-blue-300 transition-colors">
                Sign in
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
