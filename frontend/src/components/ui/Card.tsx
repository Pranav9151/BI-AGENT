import React from "react";
import { cn } from "@/lib/utils";

interface CardProps {
  children: React.ReactNode;
  className?: string;
}

export function Card({ children, className }: CardProps) {
  return (
    <div
      className={cn(
        "bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/60",
        "shadow-2xl shadow-black/30",
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className }: CardProps) {
  return (
    <div className={cn("px-8 pt-8 pb-2", className)}>{children}</div>
  );
}

export function CardContent({ children, className }: CardProps) {
  return <div className={cn("px-8 pb-8", className)}>{children}</div>;
}
