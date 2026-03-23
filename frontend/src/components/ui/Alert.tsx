import React from "react";
import { cn } from "@/lib/utils";
import { AlertCircle, CheckCircle2, Info, XCircle } from "lucide-react";

type AlertVariant = "error" | "success" | "info" | "warning";

interface AlertProps {
  variant?: AlertVariant;
  children: React.ReactNode;
  className?: string;
  onDismiss?: () => void;
}

const config: Record<
  AlertVariant,
  { icon: React.ReactNode; bg: string; border: string; text: string }
> = {
  error: {
    icon: <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />,
    bg: "bg-red-500/8",
    border: "border-red-500/20",
    text: "text-red-300",
  },
  success: {
    icon: <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />,
    bg: "bg-emerald-500/8",
    border: "border-emerald-500/20",
    text: "text-emerald-300",
  },
  info: {
    icon: <Info className="h-4 w-4 text-blue-400 shrink-0 mt-0.5" />,
    bg: "bg-blue-500/8",
    border: "border-blue-500/20",
    text: "text-blue-300",
  },
  warning: {
    icon: <AlertCircle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />,
    bg: "bg-amber-500/8",
    border: "border-amber-500/20",
    text: "text-amber-300",
  },
};

export function Alert({ variant = "info", children, className, onDismiss }: AlertProps) {
  const c = config[variant];
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2.5 px-4 py-3 rounded-lg border text-sm",
        c.bg,
        c.border,
        c.text,
        className
      )}
    >
      {c.icon}
      <div className="flex-1 min-w-0">{children}</div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-current opacity-50 hover:opacity-100 transition-opacity shrink-0"
        >
          <XCircle className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
