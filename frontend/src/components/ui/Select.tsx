import React, { forwardRef } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  label?: string;
  error?: string;
  hint?: string;
  options: SelectOption[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, hint, options, placeholder, className, id, ...props }, ref) => {
    const selectId = id || label?.toLowerCase().replace(/\s+/g, "-");

    return (
      <div className="space-y-1.5">
        {label && (
          <label
            htmlFor={selectId}
            className="block text-sm font-medium text-slate-300"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            className={cn(
              "w-full h-10 rounded-lg border bg-slate-800/60 text-slate-100 text-sm appearance-none",
              "transition-colors duration-150",
              "focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-offset-slate-900",
              error
                ? "border-red-500/60 focus:ring-red-500/40"
                : "border-slate-600/80 hover:border-slate-500 focus:ring-blue-500/40 focus:border-blue-500/60",
              "pl-3 pr-9",
              className
            )}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
        </div>
        {error && (
          <p className="text-xs text-red-400 mt-1">{error}</p>
        )}
        {hint && !error && (
          <p className="text-xs text-slate-500 mt-1">{hint}</p>
        )}
      </div>
    );
  }
);

Select.displayName = "Select";
