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

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
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
  Bookmark,
  Download,
  FileSpreadsheet,
  FileText,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError, triggerBlobDownload } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input, Select } from "@/components/ui";
import { ResultsTable, AutoChart } from "@/components/QueryResults";
import type { ConnectionListResponse } from "@/types/connections";
import type { QueryRequest, QueryResponse } from "@/types/query";
import type { SavedQueryCreateRequest } from "@/types/saved-queries";

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

// ─── Save Query Modal ──────────────────────────────────────────────────────

interface SaveQueryModalProps {
  result: QueryResponse;
  connectionId: string;
  onClose: () => void;
  onSaved: () => void;
}

function SaveQueryModal({ result, connectionId, onClose, onSaved }: SaveQueryModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [sensitivity, setSensitivity] = useState("normal");

  const saveMutation = useMutation({
    mutationFn: (body: SavedQueryCreateRequest) =>
      api.post("/saved-queries/", body),
    onSuccess: () => {
      toast.success("Query saved to library");
      onSaved();
      onClose();
    },
    onError: (err: ApiRequestError) => toast.error(err.message || "Failed to save query"),
  });

  const handleSave = () => {
    if (!name.trim()) {
      toast.error("Query name is required");
      return;
    }
    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    saveMutation.mutate({
      connection_id: connectionId,
      name: name.trim(),
      description: description.trim() || null,
      question: result.question,
      sql_query: result.sql,
      tags,
      sensitivity: sensitivity as "normal" | "sensitive" | "restricted",
      is_shared: false,
      is_pinned: false,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-md bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <div className="flex items-center gap-2">
            <Bookmark className="h-4 w-4 text-blue-400" />
            <h2 className="text-base font-semibold text-white">Save Query</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <Input
            label="Name *"
            placeholder="e.g. Monthly Revenue Report"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
          />

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-slate-300">Description</label>
            <textarea
              placeholder="Optional notes about this query…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              rows={2}
              className="w-full rounded-lg border border-slate-600/80 bg-slate-800/60 text-slate-100 text-sm placeholder:text-slate-500 px-3 py-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/60 transition-colors"
            />
          </div>

          <Input
            label="Tags"
            placeholder="Comma-separated, e.g. revenue, monthly, finance"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            hint="Helps with search and organization"
          />

          <Select
            label="Sensitivity"
            value={sensitivity}
            onChange={(e) => setSensitivity(e.target.value)}
            options={[
              { value: "normal", label: "Normal — Internal use" },
              { value: "sensitive", label: "Sensitive — Restricted distribution" },
              { value: "restricted", label: "Restricted — Authorized personnel only" },
            ]}
            hint="Controls who can view and export this query"
          />

          <div className="rounded-lg bg-slate-700/30 border border-slate-700/40 p-3">
            <p className="text-[11px] text-slate-500 mb-1">SQL Preview</p>
            <p className="text-xs text-slate-300 font-mono line-clamp-3">{result.sql}</p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 p-5 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            icon={<Bookmark className="h-3.5 w-3.5" />}
            onClick={handleSave}
            isLoading={saveMutation.isPending}
            disabled={!name.trim()}
          >
            Save Query
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Export Handler ─────────────────────────────────────────────────────────

async function handleExport(
  format: "csv" | "excel" | "pdf",
  result: QueryResponse,
) {
  try {
    // Convert row objects → array-of-arrays for export endpoint
    const rowArrays = result.rows.map((row) =>
      result.columns.map((col) => {
        const val = row[col];
        return val === null || val === undefined ? null : val;
      })
    );

    const { blob, filename } = await api.downloadBlob("/export/", {
      columns: result.columns,
      rows: rowArrays,
      format,
      sensitivity: "normal",
      filename: result.question.slice(0, 60).replace(/[^a-zA-Z0-9\s-_]/g, ""),
      title: result.question,
    });

    triggerBlobDownload(blob, filename);
    toast.success(`Exported as ${format.toUpperCase()}`);
  } catch (err) {
    const msg = err instanceof ApiRequestError ? err.message : "Export failed";
    toast.error(msg);
  }
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
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
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

                {/* ── Action Row: Save + Export ── */}
                <div className="shrink-0 flex items-center justify-between py-2 px-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Bookmark className="h-3.5 w-3.5" />}
                    onClick={() => setShowSaveModal(true)}
                  >
                    Save Query
                  </Button>
                  <div className="flex items-center gap-1">
                    <span className="text-[10px] text-slate-600 mr-1.5">Export</span>
                    {([
                      { fmt: "csv" as const, label: "CSV", icon: <Download className="h-3 w-3" /> },
                      { fmt: "excel" as const, label: "Excel", icon: <FileSpreadsheet className="h-3 w-3" /> },
                      { fmt: "pdf" as const, label: "PDF", icon: <FileText className="h-3 w-3" /> },
                    ]).map(({ fmt, label, icon }) => (
                      <button
                        key={fmt}
                        onClick={async () => {
                          setExporting(fmt);
                          await handleExport(fmt, activeResult);
                          setExporting(null);
                        }}
                        disabled={exporting !== null}
                        className={cn(
                          "flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all",
                          "bg-slate-700/40 text-slate-400 hover:bg-slate-700/70 hover:text-slate-200",
                          "disabled:opacity-40 disabled:cursor-not-allowed",
                        )}
                      >
                        {exporting === fmt ? <Loader2 className="h-3 w-3 animate-spin" /> : icon}
                        {label}
                      </button>
                    ))}
                  </div>
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

      {/* Save Query Modal */}
      {showSaveModal && activeResult && (
        <SaveQueryModal
          result={activeResult}
          connectionId={selectedConnection}
          onClose={() => setShowSaveModal(false)}
          onSaved={() => {}}
        />
      )}
    </div>
  );
}