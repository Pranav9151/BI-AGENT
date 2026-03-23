import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Smartphone, Copy, CheckCircle2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { useAuthStore } from "@/stores/auth-store";
import { AuthLayout } from "@/components/auth";
import {
  Button,
  Card,
  CardHeader,
  CardContent,
  Alert,
  Input,
} from "@/components/ui";
import { Spinner } from "@/components/ui/Spinner";
import type { TOTPSetupResponse } from "@/types/auth";

// ─── Page ────────────────────────────────────────────────────────────────────

export default function TOTPSetupPage() {
  const navigate = useNavigate();
  const {
    setupTotp,
    confirmTotp,
    phase,
    isLoading,
    error,
    clearError,
    forceLogout,
  } = useAuthStore();

  const [setupData, setSetupData] = useState<TOTPSetupResponse | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"loading" | "scan" | "confirm" | "done">(
    "loading"
  );
  const [copied, setCopied] = useState(false);

  // Guard: only accessible during totp_setup phase
  useEffect(() => {
    if (phase === "authenticated") {
      navigate("/", { replace: true });
    } else if (phase === "unauthenticated" && step === "done") {
      // After successful confirm, store moves to unauthenticated
      // Show success briefly, then redirect
      const timer = setTimeout(() => navigate("/login", { replace: true }), 2500);
      return () => clearTimeout(timer);
    } else if (phase === "unauthenticated" && step !== "done") {
      navigate("/login", { replace: true });
    }
  }, [phase, step, navigate]);

  // Fetch QR code on mount
  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      try {
        const data = await setupTotp();
        if (!cancelled) {
          setSetupData(data);
          setStep("scan");
        }
      } catch (err) {
        if (!cancelled) {
          setSetupError(
            err instanceof Error ? err.message : "Failed to generate TOTP setup"
          );
          setStep("scan"); // show error state
        }
      }
    };
    init();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const copySecret = useCallback(async () => {
    if (!setupData?.secret) return;
    try {
      await navigator.clipboard.writeText(setupData.secret);
      setCopied(true);
      toast.success("Secret copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy — please select and copy manually");
    }
  }, [setupData]);

  const handleConfirm = async () => {
    if (code.length < 6) return;
    clearError();
    try {
      await confirmTotp(code.replace(/\s/g, ""));
      setStep("done");
    } catch {
      // Error handled in store
    }
  };

  const handleCancel = () => {
    forceLogout();
    navigate("/login", { replace: true });
  };

  // ── Done State ─────────────────────────────────────────────────────────
  if (step === "done") {
    return (
      <AuthLayout>
        <Card className="w-full max-w-sm">
          <CardContent className="pt-8 text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-emerald-500/15 border border-emerald-500/20 mb-4">
              <CheckCircle2 className="h-7 w-7 text-emerald-400" />
            </div>
            <h2 className="text-lg font-semibold text-white mb-2">
              TOTP enabled successfully
            </h2>
            <p className="text-sm text-slate-400 mb-4">
              Your authenticator app is now linked. You'll be asked for a code
              on every login.
            </p>
            <p className="text-xs text-slate-500 animate-pulse">
              Redirecting to login…
            </p>
          </CardContent>
        </Card>
      </AuthLayout>
    );
  }

  // ── Loading State ──────────────────────────────────────────────────────
  if (step === "loading") {
    return (
      <AuthLayout>
        <Card className="w-full max-w-sm">
          <CardContent className="pt-8 flex flex-col items-center gap-4">
            <Spinner size="lg" />
            <p className="text-sm text-slate-400">
              Generating authenticator setup…
            </p>
          </CardContent>
        </Card>
      </AuthLayout>
    );
  }

  // ── Setup / Scan / Confirm ─────────────────────────────────────────────
  return (
    <AuthLayout>
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-amber-500/15 border border-amber-500/10 mx-auto mb-3">
            <Smartphone className="h-6 w-6 text-amber-400" />
          </div>
          <h2 className="text-lg font-semibold text-white">
            Set up two-factor authentication
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Admin accounts require TOTP for security
          </p>
        </CardHeader>

        <CardContent>
          {(error || setupError) && (
            <Alert
              variant="error"
              className="mb-5"
              onDismiss={() => {
                clearError();
                setSetupError(null);
              }}
            >
              {error || setupError}
            </Alert>
          )}

          {setupData && (
            <>
              {/* Step 1: Scan QR Code */}
              <div className="space-y-4">
                <div className="text-center">
                  <p className="text-sm text-slate-300 mb-3">
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-500/20 text-blue-400 text-xs font-bold mr-1.5">
                      1
                    </span>
                    Scan this QR code with your authenticator app
                  </p>
                  <div className="inline-block p-3 bg-white rounded-xl">
                    <img
                      src={setupData.qr_code}
                      alt="TOTP QR Code"
                      className="w-48 h-48"
                    />
                  </div>
                </div>

                {/* Manual entry fallback */}
                <div className="bg-slate-700/30 rounded-lg p-3">
                  <p className="text-xs text-slate-400 mb-2">
                    Can't scan? Enter this secret manually:
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 text-xs font-mono text-slate-200 bg-slate-800/80 px-3 py-2 rounded break-all select-all">
                      {setupData.secret}
                    </code>
                    <button
                      onClick={copySecret}
                      className="shrink-0 p-2 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
                      title="Copy secret"
                    >
                      {copied ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Step 2: Confirm with code */}
                <div className="pt-2">
                  <p className="text-sm text-slate-300 mb-3">
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-500/20 text-blue-400 text-xs font-bold mr-1.5">
                      2
                    </span>
                    Enter the code from your app to confirm
                  </p>
                  <div className="flex gap-2">
                    <Input
                      type="text"
                      inputMode="numeric"
                      maxLength={8}
                      placeholder="000 000"
                      value={code}
                      onChange={(e) =>
                        setCode(e.target.value.replace(/[^\d\s]/g, ""))
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleConfirm();
                      }}
                      icon={<ShieldCheck className="h-4 w-4" />}
                      className="font-mono text-center tracking-widest"
                      autoComplete="one-time-code"
                    />
                    <Button
                      onClick={handleConfirm}
                      isLoading={isLoading}
                      disabled={code.replace(/\s/g, "").length < 6}
                    >
                      Verify
                    </Button>
                  </div>
                </div>
              </div>
            </>
          )}

          <div className="mt-6 pt-4 border-t border-slate-700/40">
            <Button
              variant="ghost"
              size="sm"
              className="w-full"
              onClick={handleCancel}
            >
              Cancel and return to login
            </Button>
          </div>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
