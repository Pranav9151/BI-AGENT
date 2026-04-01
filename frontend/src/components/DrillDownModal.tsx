/**
 * Smart BI Agent — Conversational Drill-Down (Phase 11)
 *
 * WHAT IT DOES:
 * User clicks a bar (e.g. "Q3 Sales: $2.4M") → this modal opens asking
 * "How do you want to explore Q3 Sales?" with suggestions like
 * "by product category", "by region", "by sales rep".
 * User types or clicks → instant sub-chart renders inline.
 *
 * WHY COMPETITORS DON'T HAVE THIS:
 * - Power BI drill-down requires pre-configured hierarchies
 * - Tableau needs calculated fields set up in advance
 * - Qlik requires associative model design
 * - WE just ask the AI: "Break down Q3 Sales by product category"
 */
import { useState, useRef, useEffect } from "react";
import {
  X, Send, Loader2, Sparkles, ArrowRight,
  BarChart3, PieChart, Table2, TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, ApiRequestError } from "@/lib/api";
import { AutoChart, Scorecard, toNumber } from "@/components/QueryResults";
import type { QueryResponse } from "@/types/query";

interface DrillDownModalProps {
  label: string;        // The clicked value, e.g. "Q3" or "APAC"
  column: string;       // The column name, e.g. "quarter" or "region"
  connectionId: string;
  onClose: () => void;
}

const SUGGESTIONS = [
  { label: "by category", icon: <BarChart3 className="h-3 w-3" />, q: "Break it down by category" },
  { label: "by region", icon: <PieChart className="h-3 w-3" />, q: "Split by region" },
  { label: "over time", icon: <TrendingUp className="h-3 w-3" />, q: "Show the trend over time" },
  { label: "top 10 detail", icon: <Table2 className="h-3 w-3" />, q: "Show me the top 10 records in detail" },
];

export function DrillDownModal({ label, column, connectionId, onClose }: DrillDownModalProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  const handleQuery = async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    const fullQuestion = `For ${column} = "${label}", ${q.trim()}`;

    try {
      const res = await api.post<QueryResponse>("/query/", {
        question: fullQuestion,
        connection_id: connectionId,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = () => handleQuery(query);

  // Auto-generate insight from drill-down result
  const insight = (() => {
    if (!result || result.rows.length === 0 || result.columns.length < 2) return null;
    const vals = result.rows.map((r) => toNumber(r[result.columns[1]])).filter((v): v is number => v !== null);
    if (vals.length < 2) return null;
    const total = vals.reduce((a, b) => a + b, 0);
    const max = Math.max(...vals);
    const maxIdx = vals.indexOf(max);
    const topLabel = String(result.rows[maxIdx]?.[result.columns[0]] ?? "");
    return `Within "${label}", ${topLabel} leads at ${((max / total) * 100).toFixed(0)}% of the sub-total.`;
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-xl glass-strong rounded-2xl shadow-2xl animate-scale-in max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-slate-700/40">
          <div>
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-400" />
              Drill into: <span className="text-blue-300">{label}</span>
            </h2>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Column: {column} — ask how you want to explore this slice
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition-colors p-1"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Query Input */}
        <div className="shrink-0 px-5 py-3 border-b border-slate-700/30">
          <div className="relative">
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
              placeholder={`How do you want to explore "${label}"?`}
              className="w-full h-10 rounded-lg border border-slate-700/40 bg-slate-800/40 text-slate-200 text-sm pl-3 pr-10 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-violet-500/40 transition-all duration-200"
            />
            <button
              onClick={handleSubmit}
              disabled={!query.trim() || loading}
              className="absolute right-1.5 top-1.5 p-1.5 rounded-md bg-violet-600 text-white disabled:opacity-20 hover:bg-violet-500 transition-colors"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            </button>
          </div>

          {/* Quick suggestions */}
          {!result && !loading && (
            <div className="flex flex-wrap gap-1.5 mt-2.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.label}
                  onClick={() => { setQuery(s.q); handleQuery(s.q); }}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-medium text-slate-400 border border-slate-700/30 hover:text-violet-300 hover:border-violet-500/25 hover:bg-violet-500/5 transition-all duration-200"
                >
                  {s.icon}
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <Loader2 className="h-6 w-6 text-violet-400 animate-spin mx-auto mb-3" />
                <p className="text-xs text-slate-500">Drilling into "{label}"…</p>
              </div>
            </div>
          )}

          {error && (
            <div className="text-center py-8">
              <p className="text-xs text-red-400 mb-2">{error}</p>
              <button
                onClick={() => handleQuery(query)}
                className="text-[10px] text-blue-400 border border-blue-500/30 rounded px-3 py-1 hover:bg-blue-500/10 transition-colors"
              >
                Retry
              </button>
            </div>
          )}

          {result && (
            <div className="space-y-4 animate-fade-in">
              {/* AI Insight */}
              {insight && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-violet-500/5 border border-violet-500/10">
                  <Sparkles className="h-3.5 w-3.5 text-violet-400 shrink-0 mt-0.5" />
                  <p className="text-[11px] text-slate-300 leading-relaxed">{insight}</p>
                </div>
              )}

              {/* Chart */}
              <div className="rounded-xl border border-slate-700/25 overflow-hidden bg-slate-800/20">
                <div className="px-3 py-2 border-b border-slate-700/20">
                  <p className="text-[10px] text-slate-500">
                    {result.row_count} rows · {result.duration_ms}ms · {result.model}
                  </p>
                </div>
                <div className="p-2" style={{ height: 280 }}>
                  {result.rows.length === 1 && result.columns.length <= 3 ? (
                    <Scorecard columns={result.columns} rows={result.rows} />
                  ) : (
                    <AutoChart columns={result.columns} rows={result.rows} fillContainer />
                  )}
                </div>
              </div>

              {/* SQL */}
              <details className="group">
                <summary className="text-[9px] text-slate-600 cursor-pointer hover:text-slate-400 transition-colors select-none">
                  Show generated SQL
                </summary>
                <pre className="mt-1 text-[8px] text-slate-500 bg-slate-800/40 rounded-lg p-2 border border-slate-700/20 whitespace-pre-wrap break-all">
                  {result.sql}
                </pre>
              </details>
            </div>
          )}

          {!result && !loading && !error && (
            <div className="text-center py-8">
              <Sparkles className="h-8 w-8 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-400">Click a suggestion or type your own question</p>
              <p className="text-[10px] text-slate-600 mt-1">
                Examples: "by product category", "show monthly trend", "compare with last year"
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
