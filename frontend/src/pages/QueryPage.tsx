/**
 * Smart BI Agent — Query Page v2 (THE CORE)
 * World-class BI query workspace
 *
 * Features:
 *   - Smart suggested questions by category
 *   - Chat-style conversation history
 *   - Fixed Monaco SQL preview (dark theme, no white patch)
 *   - Robust auto-chart (handles Decimal/string numbers)
 *   - Copy SQL, metadata bar, conversation flow
 *   - Beautiful empty state with onboarding
 */

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend,
} from "recharts";
import Editor from "@monaco-editor/react";
import {
  Send,
  Database,
  Code2,
  Table2,
  BarChart3,
  Clock,
  Cpu,
  ChevronDown,
  ChevronUp,
  Loader2,
  Sparkles,
  Copy,
  Check,
  MessageSquare,
  TrendingUp,
  Users,
  ShoppingCart,
  HeadphonesIcon,
  Megaphone,
  Building2,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert } from "@/components/ui";
import type { ConnectionListResponse } from "@/types/connections";
import type { QueryRequest, QueryResponse } from "@/types/query";

// ─── Suggested Questions ────────────────────────────────────────────────────

interface SuggestionCategory {
  icon: React.ReactNode;
  label: string;
  color: string;
  questions: string[];
}

const SUGGESTION_CATEGORIES: SuggestionCategory[] = [
  {
    icon: <TrendingUp className="h-4 w-4" />,
    label: "Revenue & Sales",
    color: "from-emerald-500/20 to-emerald-600/5 border-emerald-500/20 hover:border-emerald-400/40",
    questions: [
      "What is the total revenue by month for 2024?",
      "Show me top 10 products by total sales revenue",
      "What is the average order value by payment method?",
      "Show monthly revenue trend for 2023 and 2024",
    ],
  },
  {
    icon: <Users className="h-4 w-4" />,
    label: "Customers",
    color: "from-blue-500/20 to-blue-600/5 border-blue-500/20 hover:border-blue-400/40",
    questions: [
      "How many customers do we have in each country? Top 10",
      "Show me customer distribution by industry",
      "Which tier has the highest average annual revenue?",
      "How many new customers were acquired each month in 2024?",
    ],
  },
  {
    icon: <Building2 className="h-4 w-4" />,
    label: "Employees & HR",
    color: "from-violet-500/20 to-violet-600/5 border-violet-500/20 hover:border-violet-400/40",
    questions: [
      "Show me average salary by department, highest to lowest",
      "How many employees were hired each year?",
      "What is the performance rating distribution?",
      "List departments with their budgets and head counts",
    ],
  },
  {
    icon: <HeadphonesIcon className="h-4 w-4" />,
    label: "Support",
    color: "from-amber-500/20 to-amber-600/5 border-amber-500/20 hover:border-amber-400/40",
    questions: [
      "Show me support ticket counts by priority",
      "What is the average resolution time by category?",
      "Which employees handle the most support tickets?",
      "Show me satisfaction scores by ticket category",
    ],
  },
  {
    icon: <Megaphone className="h-4 w-4" />,
    label: "Marketing",
    color: "from-rose-500/20 to-rose-600/5 border-rose-500/20 hover:border-rose-400/40",
    questions: [
      "Which marketing channels have the most conversions?",
      "Show me campaign ROI — spent vs conversions, top 10",
      "What is the lead conversion rate by source?",
      "Show lead score distribution across all campaigns",
    ],
  },
  {
    icon: <ShoppingCart className="h-4 w-4" />,
    label: "Orders",
    color: "from-cyan-500/20 to-cyan-600/5 border-cyan-500/20 hover:border-cyan-400/40",
    questions: [
      "How many orders by status?",
      "What are the top 10 customers by total spending?",
      "Show me the order count trend by month in 2024",
      "Which products are ordered most frequently?",
    ],
  },
];

// ─── Chat History Entry ─────────────────────────────────────────────────────

interface ChatEntry {
  question: string;
  response: QueryResponse;
}

// ─── Copy Button ────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-slate-700/60 text-slate-300 hover:bg-slate-600/60 hover:text-white transition-all"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied!" : "Copy SQL"}
    </button>
  );
}

// ─── Auto-chart heuristics ──────────────────────────────────────────────────

const CHART_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#06b6d4", "#ec4899", "#f97316", "#14b8a6", "#6366f1",
];

type ChartType = "bar" | "line" | "pie" | "none";

function toNumber(val: unknown): number | null {
  if (typeof val === "number") return val;
  if (typeof val === "string") {
    const n = parseFloat(val);
    return isNaN(n) ? null : n;
  }
  return null;
}

function detectChartType(columns: string[], rows: Record<string, unknown>[]): ChartType {
  if (!rows.length || columns.length < 2) return "none";
  if (rows.length > 500) return "none";

  const sample = rows.slice(0, 15);
  const secondVals = sample.map((r) => toNumber(r[columns[1]]));
  const hasNumbers = secondVals.filter((v) => v !== null).length > sample.length * 0.5;

  if (!hasNumbers) return "none";

  const firstVals = sample.map((r) => r[columns[0]]);
  const firstIsString = firstVals.every((v) => typeof v === "string" || v === null);

  if (rows.length <= 6 && firstIsString) return "pie";
  if (rows.length <= 40 && firstIsString) return "bar";
  if (rows.length > 10) return "line";

  return "bar";
}

// ─── Custom Tooltip ─────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600/60 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      {payload.map((entry: any, i: number) => (
        <p key={i} className="text-sm font-medium" style={{ color: entry.color }}>
          {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
        </p>
      ))}
    </div>
  );
}

// ─── Results Table ──────────────────────────────────────────────────────────

function ResultsTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columnHelper = createColumnHelper<Record<string, unknown>>();

  const tableColumns = useMemo(
    () =>
      columns.map((col) =>
        columnHelper.accessor(col, {
          header: col,
          cell: (info) => {
            const val = info.getValue();
            if (val === null || val === undefined)
              return <span className="text-slate-600 italic">null</span>;
            if (typeof val === "boolean")
              return (
                <span className={val ? "text-emerald-400" : "text-red-400"}>
                  {val ? "true" : "false"}
                </span>
              );
            if (typeof val === "number")
              return <span className="text-blue-300">{val.toLocaleString()}</span>;
            if (typeof val === "object") return JSON.stringify(val);
            return String(val);
          },
        })
      ),
    [columns]
  );

  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });

  return (
    <div>
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="bg-slate-800/95 backdrop-blur-sm border-b border-slate-700/40">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="text-left text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-4 py-3 cursor-pointer hover:text-slate-200 select-none whitespace-nowrap transition-colors"
                  >
                    <span className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {{
                        asc: <ChevronUp className="h-3 w-3 text-blue-400" />,
                        desc: <ChevronDown className="h-3 w-3 text-blue-400" />,
                      }[header.column.getIsSorted() as string] ?? null}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-700/20">
            {table.getRowModel().rows.map((row, idx) => (
              <tr
                key={row.id}
                className={cn(
                  "transition-colors hover:bg-blue-500/5",
                  idx % 2 === 0 ? "bg-transparent" : "bg-slate-800/20"
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className="px-4 py-2.5 text-slate-300 font-mono text-xs whitespace-nowrap max-w-[300px] truncate"
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-700/30 bg-slate-800/30">
          <span className="text-xs text-slate-500">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
            <span className="ml-2 text-slate-600">({rows.length} rows)</span>
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="text-xs px-3 py-1.5 rounded-md bg-slate-700/60 text-slate-300 hover:bg-slate-600 disabled:opacity-30 transition-colors"
            >
              ← Prev
            </button>
            <button
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="text-xs px-3 py-1.5 rounded-md bg-slate-700/60 text-slate-300 hover:bg-slate-600 disabled:opacity-30 transition-colors"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Auto Chart ─────────────────────────────────────────────────────────────

function AutoChart({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const chartType = detectChartType(columns, rows);

  if (chartType === "none") {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <BarChart3 className="h-10 w-10 text-slate-600 mb-3" />
        <p className="text-sm text-slate-400 font-medium">No chart available</p>
        <p className="text-xs text-slate-500 mt-1 max-w-sm">
          Charts work best with at least 2 columns where the second column contains numeric values.
          Try a query like "Show revenue by month" or "Count orders by status".
        </p>
      </div>
    );
  }

  const labelKey = columns[0];
  const valueKeys = columns.slice(1).filter((col) => {
    const sample = rows.slice(0, 5).map((r) => toNumber(r[col]));
    return sample.filter((v) => v !== null).length > 0;
  });

  const data = rows.slice(0, 200).map((r) => {
    const entry: Record<string, any> = { name: String(r[labelKey] ?? "") };
    valueKeys.forEach((key) => {
      entry[key] = toNumber(r[key]) ?? 0;
    });
    return entry;
  });

  const primaryKey = valueKeys[0] || "value";

  return (
    <div className="h-[340px] w-full px-2">
      <ResponsiveContainer width="100%" height="100%">
        {chartType === "pie" ? (
          <PieChart>
            <Pie
              data={data}
              dataKey={primaryKey}
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={110}
              innerRadius={50}
              paddingAngle={2}
              label={({ name, percent }) =>
                `${String(name).slice(0, 15)} (${(percent * 100).toFixed(0)}%)`
              }
              labelLine={{ stroke: "#475569", strokeWidth: 1 }}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />
          </PieChart>
        ) : chartType === "line" ? (
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#64748b" }} angle={-25} textAnchor="end" height={50} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} axisLine={{ stroke: "#334155" }} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2.5} dot={{ r: 3, fill: CHART_COLORS[i % CHART_COLORS.length] }} activeDot={{ r: 5 }} />
            ))}
            {valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#64748b" }} angle={-25} textAnchor="end" height={60} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} axisLine={{ stroke: "#334155" }} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} maxBarSize={50} />
            ))}
            {valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

// ─── Suggestion Card ────────────────────────────────────────────────────────

function SuggestionCard({ category, onSelect }: { category: SuggestionCategory; onSelect: (q: string) => void }) {
  return (
    <div className={cn("rounded-xl border bg-gradient-to-br p-4 transition-all duration-200", category.color)}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-slate-300">{category.icon}</span>
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">{category.label}</span>
      </div>
      <div className="space-y-1.5">
        {category.questions.map((q) => (
          <button key={q} onClick={() => onSelect(q)} className="w-full text-left text-[13px] text-slate-400 hover:text-white px-2.5 py-1.5 rounded-lg hover:bg-white/5 transition-all duration-150 leading-snug">
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Chat Bubble ────────────────────────────────────────────────────────────

function ChatBubble({ entry, isLatest, onViewDetails }: { entry: ChatEntry; isLatest: boolean; onViewDetails: () => void }) {
  return (
    <div className={cn("transition-all", isLatest ? "" : "opacity-70 hover:opacity-100")}>
      <div className="flex justify-end mb-2">
        <div className="max-w-[80%] bg-blue-600/20 border border-blue-500/20 rounded-2xl rounded-tr-md px-4 py-2.5">
          <p className="text-sm text-blue-100">{entry.question}</p>
        </div>
      </div>
      <div className="flex justify-start mb-4">
        <div className="max-w-[80%]">
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-2xl rounded-tl-md px-4 py-2.5">
            <div className="flex items-center gap-3 text-xs text-slate-500 mb-1">
              <span className="flex items-center gap-1"><Table2 className="h-3 w-3" />{entry.response.row_count} rows</span>
              <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{entry.response.duration_ms}ms</span>
            </div>
            {!isLatest && (
              <button onClick={onViewDetails} className="text-xs text-blue-400 hover:text-blue-300 transition-colors mt-1">
                View results →
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [selectedConnection, setSelectedConnection] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatEntry[]>([]);
  const [activeResult, setActiveResult] = useState<QueryResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"table" | "chart" | "sql">("table");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const { data: connData } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionListResponse>("/connections/"),
  });

  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];

  useEffect(() => {
    if (connections.length > 0 && !selectedConnection) {
      setSelectedConnection(connections[0].connection_id);
    }
  }, [connections, selectedConnection]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory.length]);

  const queryMutation = useMutation({
    mutationFn: (req: QueryRequest) => api.post<QueryResponse>("/query/", req),
    onSuccess: (data) => {
      setChatHistory((prev) => [...prev, { question: data.question, response: data }]);
      setActiveResult(data);
      setConversationId(data.conversation_id);
      setQuestion("");
      setActiveTab("table");
    },
    onError: (err: ApiRequestError) => {
      toast.error(err.message || "Query failed");
    },
  });

  const handleSubmit = useCallback(
    (q?: string) => {
      const text = (q || question).trim();
      if (!text || !selectedConnection) return;
      queryMutation.mutate({ question: text, connection_id: selectedConnection, conversation_id: conversationId });
      if (q) setQuestion("");
    },
    [question, selectedConnection, conversationId, queryMutation]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  };

  const handleNewConversation = () => {
    setConversationId(null);
    setChatHistory([]);
    setActiveResult(null);
    setQuestion("");
    inputRef.current?.focus();
  };

  const showWelcome = chatHistory.length === 0 && !queryMutation.isPending;

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)]">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0 mb-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-blue-400" />AI Query
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">Ask questions in plain English — get instant SQL-backed answers</p>
        </div>
        {conversationId && (
          <Button variant="ghost" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={handleNewConversation}>
            New Chat
          </Button>
        )}
      </div>

      {/* Connection Selector */}
      <div className="shrink-0 mb-3">
        <div className="flex items-center gap-2 px-1">
          <Database className="h-3.5 w-3.5 text-slate-500 shrink-0" />
          <select
            value={selectedConnection}
            onChange={(e) => { setSelectedConnection(e.target.value); handleNewConversation(); }}
            className="flex-1 h-8 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-300 text-xs px-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500/40 transition-colors"
          >
            <option value="" disabled>Select a database connection…</option>
            {connections.map((c) => (
              <option key={c.connection_id} value={c.connection_id}>{c.name} ({c.db_type})</option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 min-h-0 flex flex-col">
        {/* Welcome with Suggestions */}
        {showWelcome && (
          <div className="flex-1 overflow-y-auto pb-4">
            <div className="text-center mb-6 mt-4">
              <div className="mx-auto w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500/15 to-indigo-500/10 border border-blue-500/15 flex items-center justify-center mb-3">
                <MessageSquare className="h-6 w-6 text-blue-400" />
              </div>
              <h2 className="text-base font-semibold text-slate-200">What would you like to know?</h2>
              <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
                Click any question below or type your own. Smart BI Agent generates SQL, executes it, and shows you results with charts — instantly.
              </p>
            </div>
            {connections.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {SUGGESTION_CATEGORIES.map((cat) => (
                  <SuggestionCard key={cat.label} category={cat} onSelect={(q) => { setQuestion(q); handleSubmit(q); }} />
                ))}
              </div>
            ) : (
              <Card className="p-8 text-center">
                <Database className="h-8 w-8 text-slate-600 mx-auto mb-3" />
                <p className="text-sm text-slate-400 font-medium">No connections yet</p>
                <p className="text-xs text-slate-500 mt-1">Go to Connections → Add Connection to get started</p>
              </Card>
            )}
          </div>
        )}

        {/* Chat + Results */}
        {!showWelcome && (
          <div className="flex-1 min-h-0 flex flex-col">
            {chatHistory.length > 1 && (
              <div className="overflow-y-auto max-h-[200px] mb-3 px-1">
                {chatHistory.slice(0, -1).map((entry, i) => (
                  <ChatBubble key={i} entry={entry} isLatest={false} onViewDetails={() => { setActiveResult(entry.response); setActiveTab("table"); }} />
                ))}
                <div ref={chatEndRef} />
              </div>
            )}

            {chatHistory.length > 0 && (
              <div className="shrink-0 px-1 mb-3">
                <div className="flex justify-end">
                  <div className="max-w-[80%] bg-blue-600/20 border border-blue-500/20 rounded-2xl rounded-tr-md px-4 py-2.5">
                    <p className="text-sm text-blue-100">{chatHistory[chatHistory.length - 1].question}</p>
                  </div>
                </div>
              </div>
            )}

            {queryMutation.isPending && (
              <div className="shrink-0 flex justify-start px-1 mb-3">
                <div className="bg-slate-800/60 border border-slate-700/40 rounded-2xl rounded-tl-md px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                    <span className="text-xs text-slate-500">Generating SQL and querying database…</span>
                  </div>
                </div>
              </div>
            )}

            {queryMutation.error && !queryMutation.isPending && (
              <Alert variant="error" className="shrink-0 mb-3">
                {(queryMutation.error as ApiRequestError)?.message ?? "Query failed"}
              </Alert>
            )}

            {activeResult && !queryMutation.isPending && (
              <div className="flex-1 min-h-0 flex flex-col">
                <div className="shrink-0 flex items-center justify-between mb-2 px-1">
                  <div className="flex items-center gap-4 text-[11px] text-slate-500">
                    <span className="flex items-center gap-1 font-medium text-slate-400">
                      <Table2 className="h-3 w-3" />{activeResult.row_count} row{activeResult.row_count !== 1 ? "s" : ""}
                      {activeResult.truncated && <span className="text-amber-400 ml-0.5">(truncated)</span>}
                    </span>
                    <span className="flex items-center gap-1"><Clock className="h-3 w-3" />Query {activeResult.duration_ms}ms</span>
                    <span className="flex items-center gap-1"><Cpu className="h-3 w-3" />LLM {activeResult.llm_latency_ms}ms</span>
                    <span className="text-slate-600">{activeResult.model}</span>
                  </div>
                </div>

                <div className="shrink-0 flex items-center justify-between border-b border-slate-700/40">
                  <div className="flex">
                    {([
                      { id: "table" as const, label: "Results", icon: <Table2 className="h-3.5 w-3.5" /> },
                      { id: "chart" as const, label: "Chart", icon: <BarChart3 className="h-3.5 w-3.5" /> },
                      { id: "sql" as const, label: "SQL", icon: <Code2 className="h-3.5 w-3.5" /> },
                    ]).map((tab) => (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={cn(
                          "flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 -mb-px transition-all",
                          activeTab === tab.id ? "border-blue-500 text-blue-400" : "border-transparent text-slate-500 hover:text-slate-300",
                        )}
                      >
                        {tab.icon}{tab.label}
                      </button>
                    ))}
                  </div>
                  {activeTab === "sql" && <CopyButton text={activeResult.sql} />}
                </div>

                <Card className="flex-1 min-h-0 overflow-hidden rounded-t-none border-t-0">
                  {activeTab === "table" && <ResultsTable columns={activeResult.columns} rows={activeResult.rows} />}
                  {activeTab === "chart" && (
                    <div className="p-4"><AutoChart columns={activeResult.columns} rows={activeResult.rows} /></div>
                  )}
                  {activeTab === "sql" && (
                    <div className="h-[280px]">
                      <Editor
                        height="100%"
                        defaultLanguage="sql"
                        value={activeResult.sql}
                        theme="vs-dark"
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 13,
                          lineNumbers: "on",
                          scrollBeyondLastLine: false,
                          wordWrap: "on",
                          padding: { top: 16, bottom: 16 },
                          renderLineHighlight: "none",
                          overviewRulerBorder: false,
                          hideCursorInOverviewRuler: true,
                          scrollbar: { vertical: "hidden", horizontal: "auto", useShadows: false },
                        }}
                        onMount={(editor) => {
                          const domNode = editor.getDomNode();
                          if (domNode) domNode.style.background = "transparent";
                        }}
                      />
                    </div>
                  )}
                </Card>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Input Bar */}
      <div className="shrink-0 mt-3">
        <div className="relative">
          <textarea
            ref={inputRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={!selectedConnection ? "Add a database connection first…" : conversationId ? "Ask a follow-up question…" : "Ask a question about your data…"}
            disabled={!selectedConnection || queryMutation.isPending}
            rows={1}
            maxLength={2000}
            className={cn(
              "w-full rounded-xl border bg-slate-800/60 text-slate-100 text-sm",
              "placeholder:text-slate-500 resize-none px-4 py-3.5 pr-14",
              "focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500/50",
              "border-slate-700/60 disabled:opacity-40 transition-all",
            )}
            style={{ minHeight: "48px" }}
          />
          <button
            onClick={() => handleSubmit()}
            disabled={!question.trim() || !selectedConnection || queryMutation.isPending}
            className={cn(
              "absolute right-2.5 bottom-2.5 p-2 rounded-lg transition-all",
              "disabled:opacity-20 disabled:cursor-not-allowed",
              question.trim() ? "bg-blue-600 text-white hover:bg-blue-500 shadow-lg shadow-blue-600/25" : "bg-slate-700/60 text-slate-500",
            )}
          >
            {queryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        <div className="flex items-center justify-between mt-1 px-1">
          <span className="text-[10px] text-slate-600">
            {conversationId ? (
              <span className="flex items-center gap-1"><MessageSquare className="h-2.5 w-2.5" />Follow-up · {chatHistory.length} turn{chatHistory.length !== 1 ? "s" : ""}</span>
            ) : "Enter ↵ to send · Shift+Enter for newline"}
          </span>
          <span className={cn("text-[10px]", question.length > 1800 ? "text-amber-400" : "text-slate-600")}>
            {question.length > 0 ? `${question.length}/2000` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}