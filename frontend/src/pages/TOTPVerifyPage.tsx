import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";

import { useAuthStore } from "@/stores/auth-store";
import { AuthLayout } from "@/components/auth";
import { Button, Card, CardHeader, CardContent, Alert } from "@/components/ui";

/**
 * 6-digit TOTP input with individual character boxes.
 * Auto-advances focus, supports paste, and backspace navigation.
 */
function TOTPCodeInput({
  onComplete,
  disabled,
}: {
  onComplete: (code: string) => void;
  disabled: boolean;
}) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const refs = useRef<(HTMLInputElement | null)[]>(Array(6).fill(null));

  const handleChange = useCallback(
    (index: number, value: string) => {
      // Filter to digits only
      const clean = value.replace(/\D/g, "");
      if (!clean) return;

      const newDigits = [...digits];

      // Handle paste of full code
      if (clean.length >= 6) {
        const code = clean.slice(0, 6);
        for (let i = 0; i < 6; i++) newDigits[i] = code[i] || "";
        setDigits(newDigits);
        refs.current[5]?.focus();
        onComplete(newDigits.join(""));
        return;
      }

      // Single character
      newDigits[index] = clean[0];
      setDigits(newDigits);

      // Auto-advance
      if (index < 5) {
        refs.current[index + 1]?.focus();
      }

      // Check if complete
      if (newDigits.every((d) => d !== "")) {
        onComplete(newDigits.join(""));
      }
    },
    [digits, onComplete]
  );

  const handleKeyDown = useCallback(
    (index: number, e: React.KeyboardEvent) => {
      if (e.key === "Backspace") {
        e.preventDefault();
        const newDigits = [...digits];
        if (digits[index]) {
          newDigits[index] = "";
          setDigits(newDigits);
        } else if (index > 0) {
          newDigits[index - 1] = "";
          setDigits(newDigits);
          refs.current[index - 1]?.focus();
        }
      }
      if (e.key === "ArrowLeft" && index > 0) {
        refs.current[index - 1]?.focus();
      }
      if (e.key === "ArrowRight" && index < 5) {
        refs.current[index + 1]?.focus();
      }
    },
    [digits]
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      e.preventDefault();
      const pasted = e.clipboardData.getData("text").replace(/\D/g, "");
      if (pasted.length >= 6) {
        const code = pasted.slice(0, 6);
        const newDigits = code.split("");
        setDigits(newDigits);
        refs.current[5]?.focus();
        onComplete(newDigits.join(""));
      }
    },
    [onComplete]
  );

  return (
    <div className="flex gap-2 justify-center" onPaste={handlePaste}>
      {Array.from({ length: 6 }).map((_, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          type="text"
          inputMode="numeric"
          maxLength={1}
          disabled={disabled}
          value={digits[i]}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onFocus={(e) => e.target.select()}
          className={
            "w-11 h-13 text-center text-xl font-mono font-semibold rounded-lg " +
            "bg-slate-800/60 border border-slate-600/80 text-white " +
            "focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/60 " +
            "disabled:opacity-50 transition-colors"
          }
          autoComplete="one-time-code"
          autoFocus={i === 0}
        />
      ))}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function TOTPVerifyPage() {
  const navigate = useNavigate();
  const { verifyTotp, phase, isLoading, error, clearError, forceLogout } =
    useAuthStore();

  // Guard: only accessible during totp_verify phase
  useEffect(() => {
    if (phase === "authenticated") {
      navigate("/", { replace: true });
    } else if (phase === "unauthenticated") {
      navigate("/login", { replace: true });
    }
  }, [phase, navigate]);

  const handleComplete = async (code: string) => {
    clearError();
    try {
      await verifyTotp(code);
    } catch {
      // Error handled in store
    }
  };

  const handleCancel = () => {
    forceLogout();
    navigate("/login", { replace: true });
  };

  return (
    <AuthLayout>
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-indigo-500/15 border border-indigo-500/10 mx-auto mb-3">
            <ShieldCheck className="h-6 w-6 text-indigo-400" />
          </div>
          <h2 className="text-lg font-semibold text-white">
            Two-factor authentication
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Enter the 6-digit code from your authenticator app
          </p>
        </CardHeader>

        <CardContent>
          {error && (
            <Alert variant="error" className="mb-5" onDismiss={clearError}>
              {error}
            </Alert>
          )}

          <div className="py-4">
            <TOTPCodeInput onComplete={handleComplete} disabled={isLoading} />
          </div>

          {isLoading && (
            <p className="text-center text-sm text-slate-400 animate-pulse mt-2">
              Verifying…
            </p>
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
