/**
 * Smart BI Agent — NLFilterBar
 * Natural language filter input for dashboards.
 *
 * Users type in plain English: "show Q4 only", "exclude returns",
 * "last 30 days", "where region = North". The component parses
 * common filter patterns client-side for instant feedback, and
 * falls back to the LLM for complex filters.
 *
 * ★ DIFFERENTIATOR: No BI tool lets you type "last month" and
 *   have all widgets update instantly.
 */

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { Search, X, Filter, Sparkles, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ParsedFilter {
  column: string;
  operator: string;
  value: string;
  display: string;
  source: "parsed" | "ai";
}

// ─── Client-Side Filter Parsing ──────────────────────────────────────────────

const TIME_PATTERNS: [RegExp, (m: RegExpMatchArray) => ParsedFilter | null][] = [
  [
    /^(?:last|past)\s+(\d+)\s+(days?|weeks?|months?|years?)$/i,
    (m) => {
      const n = parseInt(m[1]);
      const unit = m[2].replace(/s$/, "");
      const d = new Date();
      if (unit === "day") d.setDate(d.getDate() - n);
      else if (unit === "week") d.setDate(d.getDate() - n * 7);
      else if (unit === "month") d.setMonth(d.getMonth() - n);
      else if (unit === "year") d.setFullYear(d.getFullYear() - n);
      return {
        column: "__date__",
        operator: ">=",
        value: d.toISOString().split("T")[0],
        display: `Last ${n} ${m[2]}`,
        source: "parsed",
      };
    },
  ],
  [
    /^(?:this|current)\s+(week|month|quarter|year)$/i,
    (m) => {
      const unit = m[1].toLowerCase();
      const now = new Date();
      let start: Date;
      if (unit === "week") {
        start = new Date(now);
        start.setDate(now.getDate() - now.getDay());
      } else if (unit === "month") {
        start = new Date(now.getFullYear(), now.getMonth(), 1);
      } else if (unit === "quarter") {
        const qMonth = Math.floor(now.getMonth() / 3) * 3;
        start = new Date(now.getFullYear(), qMonth, 1);
      } else {
        start = new Date(now.getFullYear(), 0, 1);
      }
      return {
        column: "__date__",
        operator: ">=",
        value: start.toISOString().split("T")[0],
        display: `This ${unit}`,
        source: "parsed",
      };
    },
  ],
  [
    /^Q([1-4])(?:\s+(\d{4}))?$/i,
    (m) => {
      const q = parseInt(m[1]);
      const year = m[2] ? parseInt(m[2]) : new Date().getFullYear();
      const startMonth = (q - 1) * 3;
      const endMonth = startMonth + 3;
      return {
        column: "__date__",
        operator: "BETWEEN",
        value: `${year}-${String(startMonth + 1).padStart(2, "0")}-01 AND ${year}-${String(endMonth).padStart(2, "0")}-${endMonth === 12 ? 31 : new Date(year, endMonth, 0).getDate()}`,
        display: `Q${q} ${year}`,
        source: "parsed",
      };
    },
  ],
];

const VALUE_PATTERNS: [RegExp, (m: RegExpMatchArray) => ParsedFilter | null][] = [
  [
    /^(?:where|filter|show)\s+(\w+)\s*=\s*['"]?(.+?)['"]?$/i,
    (m) => ({
      column: m[1],
      operator: "=",
      value: m[2].trim(),
      display: `${m[1]} = "${m[2].trim()}"`,
      source: "parsed",
    }),
  ],
  [
    /^(?:exclude|remove|hide|not)\s+['"]?(.+?)['"]?$/i,
    (m) => ({
      column: "__auto__",
      operator: "!=",
      value: m[1].trim(),
      display: `Exclude "${m[1].trim()}"`,
      source: "parsed",
    }),
  ],
  [
    /^(?:only|show only|just)\s+['"]?(.+?)['"]?$/i,
    (m) => ({
      column: "__auto__",
      operator: "=",
      value: m[1].trim(),
      display: `Only "${m[1].trim()}"`,
      source: "parsed",
    }),
  ],
  [
    /^top\s+(\d+)$/i,
    (m) => ({
      column: "__limit__",
      operator: "LIMIT",
      value: m[1],
      display: `Top ${m[1]}`,
      source: "parsed",
    }),
  ],
];

function parseFilterText(text: string): ParsedFilter | null {
  const trimmed = text.trim();
  if (!trimmed) return null;

  // Try time patterns
  for (const [re, fn] of TIME_PATTERNS) {
    const m = trimmed.match(re);
    if (m) return fn(m);
  }

  // Try value patterns
  for (const [re, fn] of VALUE_PATTERNS) {
    const m = trimmed.match(re);
    if (m) return fn(m);
  }

  return null;
}

// ─── Suggestions ─────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "Last 30 days",
  "This month",
  "This quarter",
  "Q4 2025",
  "Top 10",
  "Exclude null",
];

// ─── Component ───────────────────────────────────────────────────────────────

interface NLFilterBarProps {
  activeFilters: ParsedFilter[];
  onAddFilter: (filter: ParsedFilter) => void;
  onRemoveFilter: (index: number) => void;
  onClearAll: () => void;
  className?: string;
}

export function NLFilterBar({
  activeFilters,
  onAddFilter,
  onRemoveFilter,
  onClearAll,
  className,
}: NLFilterBarProps) {
  const [input, setInput] = useState("");
  const [focused, setFocused] = useState(false);
  const [parsing, setParsing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const preview = useMemo(() => {
    if (!input.trim()) return null;
    return parseFilterText(input);
  }, [input]);

  const handleSubmit = useCallback(() => {
    if (!input.trim()) return;

    const parsed = parseFilterText(input);
    if (parsed) {
      onAddFilter(parsed);
      setInput("");
      return;
    }

    // Mark as AI filter (would be sent to backend in production)
    onAddFilter({
      column: "__ai__",
      operator: "AI",
      value: input.trim(),
      display: input.trim(),
      source: "ai",
    });
    setInput("");
  }, [input, onAddFilter]);

  const handleSuggestion = useCallback(
    (s: string) => {
      const parsed = parseFilterText(s);
      if (parsed) {
        onAddFilter(parsed);
      }
    },
    [onAddFilter]
  );

  return (
    <div className={cn("space-y-2", className)}>
      {/* Input Row */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Filter className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-600" />
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 200)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
              if (e.key === "Escape") {
                setInput("");
                inputRef.current?.blur();
              }
            }}
            placeholder="Filter: &quot;last 30 days&quot;, &quot;Q4 2025&quot;, &quot;exclude returns&quot;…"
            className="w-full h-8 rounded-lg border border-slate-700/30 bg-slate-800/30 text-[11px] text-slate-300 pl-8 pr-20 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/20 transition-all duration-200"
          />

          {/* Live preview badge */}
          {preview && input && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              ✓ {preview.display}
            </span>
          )}
          {input && !preview && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-500/20 flex items-center gap-1">
              <Sparkles className="h-2.5 w-2.5" /> AI filter
            </span>
          )}
        </div>

        {activeFilters.length > 0 && (
          <button
            onClick={onClearAll}
            className="text-[9px] text-slate-500 hover:text-red-400 border border-slate-700/20 rounded px-2 py-1.5 hover:bg-red-500/5 transition-colors"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Suggestions (when focused and empty) */}
      {focused && !input && activeFilters.length === 0 && (
        <div className="flex flex-wrap gap-1.5 animate-fade-in">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => handleSuggestion(s)}
              className="text-[9px] px-2 py-1 rounded-lg border border-slate-700/30 text-slate-500 hover:text-blue-300 hover:border-blue-500/20 transition-all duration-200"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Active Filters */}
      {activeFilters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {activeFilters.map((f, i) => (
            <span
              key={i}
              className={cn(
                "inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border text-[10px] font-medium",
                f.source === "ai"
                  ? "bg-violet-600/15 text-violet-300 border-violet-500/20"
                  : "bg-blue-600/15 text-blue-300 border-blue-500/20"
              )}
            >
              {f.source === "ai" && (
                <Sparkles className="h-2.5 w-2.5 text-violet-400" />
              )}
              {f.display}
              <button
                onClick={() => onRemoveFilter(i)}
                className="hover:text-red-300 transition-colors"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
