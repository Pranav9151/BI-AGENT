import { useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Mail, Lock } from "lucide-react";

import { useAuthStore } from "@/stores/auth-store";
import { AuthLayout } from "@/components/auth";
import { Button, Input, Card, CardHeader, CardContent, Alert } from "@/components/ui";

// ─── Validation Schema ───────────────────────────────────────────────────────

const loginSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Please enter a valid email address"),
  password: z
    .string()
    .min(1, "Password is required")
    .max(128, "Password is too long"),
});

type LoginFormData = z.infer<typeof loginSchema>;

// ─── Component ───────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, phase, isLoading, error, clearError } = useAuthStore();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || "/";

  // Redirect if already authenticated
  useEffect(() => {
    if (phase === "authenticated") {
      navigate(from, { replace: true });
    } else if (phase === "totp_verify") {
      navigate("/auth/totp-verify", { replace: true });
    } else if (phase === "totp_setup") {
      navigate("/auth/totp-setup", { replace: true });
    }
  }, [phase, navigate, from]);

  const {
    register,
    handleSubmit,
    formState: { errors: formErrors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = async (data: LoginFormData) => {
    clearError();
    try {
      await login(data);
    } catch {
      // Error is set in the store — no additional handling needed
    }
  };

  return (
    <AuthLayout>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white">Sign in</h2>
          <p className="text-sm text-slate-400 mt-1">
            Enter your credentials to access the platform
          </p>
        </CardHeader>

        <CardContent>
          {error && (
            <Alert variant="error" className="mb-5" onDismiss={clearError}>
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <Input
              label="Email"
              type="email"
              placeholder="you@company.com"
              autoComplete="email"
              autoFocus
              icon={<Mail className="h-4 w-4" />}
              error={formErrors.email?.message}
              {...register("email")}
            />

            <Input
              label="Password"
              type="password"
              placeholder="••••••••"
              autoComplete="current-password"
              icon={<Lock className="h-4 w-4" />}
              error={formErrors.password?.message}
              {...register("password")}
            />

            <Button
              type="submit"
              className="w-full mt-2"
              size="lg"
              isLoading={isLoading}
            >
              Sign in
            </Button>
          </form>

          <div className="mt-5 pt-4 border-t border-slate-700/40">
            <p className="text-xs text-slate-500 text-center">
              Don&apos;t have an account?{" "}
              <Link to="/register" className="text-blue-400 hover:text-blue-300 transition-colors">
                Register with company email
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
