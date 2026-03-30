/**
 * Smart BI Agent — Query Page v4 (THE CORE)
 * Compact layout — maximum result space
 *
 * Layout:
 *   Row 1: Compact bar (connection + input + send) — 48px
 *   Row 2: Turn navigator (if multi-turn) — 32px
 *   Row 3: Tabs + actions — 40px
 *   Row 4: FULL remaining height → results/chart/studio/sql
 *
 * Total chrome: ~120px (was ~350px) → 3x more space for content
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import {
  Send, Database, Code2, Table2, BarChart3, Clock, Cpu, Loader2,
  Sparkles, Copy, Check, MessageSquare, TrendingUp, Users,
  ShoppingCart, HeadphonesIcon, Megaphone, Building2, RotateCcw,
  Bookmark, Download, FileSpreadsheet, FileText, X, Package,
  MapPin, Activity, FolderOpen, ChevronLeft, ChevronRight,
  Maximize2, Minimize2, Palette, MoreHorizontal, Save,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError, triggerBlobDownload } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Alert, Input, Select } from "@/components/ui";
import { ResultsTable, AutoChart } from "@/components/QueryResults";
import ChartStudio from "@/components/ChartStudio";
import type { ConnectionListResponse } from "@/types/connections";
import type { QueryRequest, QueryResponse, SuggestionsResponse, SuggestionCategory } from "@/types/query";
import type { SavedQueryCreateRequest } from "@/types/saved-queries";

// ─── Icon/Color Mapping ─────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ReactNode> = {
  "trending-up": <TrendingUp className="h-4 w-4" />, "users": <Users className="h-4 w-4" />,
  "building": <Building2 className="h-4 w-4" />, "headphones": <HeadphonesIcon className="h-4 w-4" />,
  "megaphone": <Megaphone className="h-4 w-4" />, "shopping-cart": <ShoppingCart className="h-4 w-4" />,
  "package": <Package className="h-4 w-4" />, "folder": <FolderOpen className="h-4 w-4" />,
  "activity": <Activity className="h-4 w-4" />, "map-pin": <MapPin className="h-4 w-4" />,
  "database": <Database className="h-4 w-4" />,
};

const COLOR_MAP: Record<string, string> = {
  emerald: "from-emerald-500/20 to-emerald-600/5 border-emerald-500/20 hover:border-emerald-400/40",
  blue: "from-blue-500/20 to-blue-600/5 border-blue-500/20 hover:border-blue-400/40",
  violet: "from-violet-500/20 to-violet-600/5 border-violet-500/20 hover:border-violet-400/40",
  amber: "from-amber-500/20 to-amber-600/5 border-amber-500/20 hover:border-amber-400/40",
  rose: "from-rose-500/20 to-rose-600/5 border-rose-500/20 hover:border-rose-400/40",
  cyan: "from-cyan-500/20 to-cyan-600/5 border-cyan-500/20 hover:border-cyan-400/40",
  indigo: "from-indigo-500/20 to-indigo-600/5 border-indigo-500/20 hover:border-indigo-400/40",
  orange: "from-orange-500/20 to-orange-600/5 border-orange-500/20 hover:border-orange-400/40",
  teal: "from-teal-500/20 to-teal-600/5 border-teal-500/20 hover:border-teal-400/40",
  slate: "from-slate-500/20 to-slate-600/5 border-slate-500/20 hover:border-slate-400/40",
};

// ─── Types ──────────────────────────────────────────────────────────────────

interface ChatEntry { question: string; response: QueryResponse; }

type TabId = "table" | "chart" | "studio" | "sql";

// ─── Copy Button ────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); };
  return (
    <button onClick={handleCopy} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium bg-slate-700/60 text-slate-300 hover:bg-slate-600/60 hover:text-white transition-all">
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}{copied ? "Copied" : "Copy"}
    </button>
  );
}

// ─── Save Modal ─────────────────────────────────────────────────────────────

function SaveQueryModal({ result, connectionId, onClose }: { result: QueryResponse; connectionId: string; onClose: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [sensitivity, setSensitivity] = useState("normal");

  const saveMutation = useMutation({
    mutationFn: (body: SavedQueryCreateRequest) => api.post("/saved-queries/", body),
    onSuccess: () => { toast.success("Query saved"); onClose(); },
    onError: (err: ApiRequestError) => toast.error(err.message),
  });

  const handleSave = () => {
    if (!name.trim()) { toast.error("Name required"); return; }
    saveMutation.mutate({
      connection_id: connectionId, name: name.trim(),
      description: description.trim() || null, question: result.question,
      sql_query: result.sql, tags: tagsInput.split(",").map((t) => t.trim()).filter(Boolean),
      sensitivity: sensitivity as "normal" | "sensitive" | "restricted",
      is_shared: false, is_pinned: false,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md glass-strong rounded-2xl shadow-2xl animate-page-in">
        <div className="flex items-center justify-between p-4 border-b border-slate-700/40">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Bookmark className="h-4 w-4 text-blue-400" />Save Query</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4 space-y-3">
          <Input label="Name *" placeholder="e.g. Monthly Revenue" value={name} onChange={(e) => setName(e.target.value)} />
          <Input label="Description" placeholder="Optional notes" value={description} onChange={(e) => setDescription(e.target.value)} />
          <Input label="Tags" placeholder="Comma-separated" value={tagsInput} onChange={(e) => setTagsInput(e.target.value)} />
          <Select label="Sensitivity" value={sensitivity} onChange={(e) => setSensitivity(e.target.value)}
            options={[{ value: "normal", label: "Normal" }, { value: "sensitive", label: "Sensitive" }, { value: "restricted", label: "Restricted" }]} />
        </div>
        <div className="flex justify-end gap-2 p-4 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleSave} isLoading={saveMutation.isPending} disabled={!name.trim()}>Save</Button>
        </div>
      </div>
    </div>
  );
}

// ─── Export ──────────────────────────────────────────────────────────────────

async function handleExport(format: "csv" | "excel" | "pdf", result: QueryResponse) {
  try {
    const rowArrays = result.rows.map((row) => result.columns.map((col) => row[col] ?? null));
    const { blob, filename } = await api.downloadBlob("/export/", {
      columns: result.columns, rows: rowArrays, format, sensitivity: "normal",
      filename: result.question.slice(0, 60).replace(/[^a-zA-Z0-9\s\-_]/g, ""), title: result.question,
    });
    triggerBlobDownload(blob, filename);
    toast.success(`Exported ${format.toUpperCase()}`);
  } catch (err) { toast.error(err instanceof ApiRequestError ? err.message : "Export failed"); }
}

// ─── Suggestion Card ────────────────────────────────────────────────────────

function SuggestionCard({ category, onSelect }: { category: SuggestionCategory; onSelect: (q: string) => void }) {
  return (
    <div className={cn("rounded-xl border bg-gradient-to-br p-4 transition-all duration-200", COLOR_MAP[category.color] || COLOR_MAP.slate)}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-slate-300">{ICON_MAP[category.icon] || ICON_MAP.database}</span>
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">{category.label}</span>
      </div>
      <div className="space-y-1.5">
        {category.questions.map((q) => (
          <button key={q} onClick={() => onSelect(q)} className="w-full text-left text-[13px] text-slate-400 hover:text-white px-2.5 py-1.5 rounded-lg hover:bg-white/5 transition-all leading-snug">
            {q}
          </button>
        ))}
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
  const [activeIdx, setActiveIdx] = useState(0);
  const [activeTab, setActiveTab] = useState<TabId>("table");
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const activeResult = chatHistory.length > 0 ? chatHistory[activeIdx]?.response ?? null : null;

  const { data: connData } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionListResponse>("/connections/"),
  });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];

  useEffect(() => {
    if (connections.length > 0 && !selectedConnection) setSelectedConnection(connections[0].connection_id);
  }, [connections, selectedConnection]);

  const { data: suggestionsData } = useQuery({
    queryKey: ["suggestions", selectedConnection],
    queryFn: () => api.get<SuggestionsResponse>(`/query/suggestions?connection_id=${selectedConnection}`),
    enabled: !!selectedConnection,
  });

  const queryMutation = useMutation({
    mutationFn: (req: QueryRequest) => api.post<QueryResponse>("/query/", req),
    onSuccess: (data) => {
      const h = [...chatHistory, { question: data.question, response: data }];
      setChatHistory(h);
      setActiveIdx(h.length - 1);
      setConversationId(data.conversation_id);
      setQuestion("");
      setActiveTab("table");
    },
    onError: (err: ApiRequestError) => toast.error(err.message || "Query failed"),
  });

  const handleSubmit = useCallback((q?: string) => {
    const text = (q || question).trim();
    if (!text || !selectedConnection) return;
    queryMutation.mutate({ question: text, connection_id: selectedConnection, conversation_id: conversationId });
    if (q) setQuestion("");
  }, [question, selectedConnection, conversationId, queryMutation]);

  const handleNewChat = () => {
    setConversationId(null); setChatHistory([]); setActiveIdx(0); setQuestion(""); inputRef.current?.focus();
  };

  const showWelcome = chatHistory.length === 0 && !queryMutation.isPending;
  const suggestions = suggestionsData?.categories ?? [];

  return (
    <div className={cn(
      "flex flex-col overflow-hidden",
      expanded ? "fixed inset-0 z-40 bg-slate-900 p-3" : "h-[calc(100vh-6.5rem)]",
    )}>
      {/* ── Row 1: Compact Query Bar ── */}
      <div className="shrink-0 flex items-center gap-2 mb-2">
        <Sparkles className="h-4 w-4 text-blue-400 shrink-0" />

        <select value={selectedConnection}
          onChange={(e) => { setSelectedConnection(e.target.value); handleNewChat(); }}
          className="w-40 shrink-0 h-9 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-300 text-xs px-2 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500/40">
          <option value="" disabled>Connection…</option>
          {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name}</option>)}
        </select>

        <div className="flex-1 relative">
          <input ref={inputRef} value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleSubmit(); } }}
            placeholder={!selectedConnection ? "Select a connection…" : conversationId ? "Follow-up question…" : "Ask about your data…"}
            disabled={!selectedConnection || queryMutation.isPending}
            maxLength={2000}
            className="w-full h-9 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-200 text-sm pl-3 pr-10 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40 disabled:opacity-40"
          />
          <button onClick={() => handleSubmit()}
            disabled={!question.trim() || !selectedConnection || queryMutation.isPending}
            className="absolute right-1.5 top-1.5 p-1.5 rounded-md bg-blue-600 text-white disabled:opacity-20 hover:bg-blue-500 transition-all">
            {queryMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          </button>
        </div>

        {conversationId && (
          <button onClick={handleNewChat} className="shrink-0 p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors" title="New chat">
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        )}

        {chatHistory.length > 0 && (
          <span className="shrink-0 text-[10px] text-slate-600">{chatHistory.length} turn{chatHistory.length !== 1 ? "s" : ""}</span>
        )}
      </div>

      {/* ── Welcome Suggestions ── */}
      {showWelcome && (
        <div className="flex-1 overflow-y-auto">
          <div className="text-center mb-6 mt-8">
            <MessageSquare className="h-8 w-8 text-blue-400 mx-auto mb-3" />
            <h2 className="text-base font-semibold text-slate-200">What would you like to know?</h2>
            <p className="text-xs text-slate-500 mt-1">Suggestions based on your data access</p>
          </div>
          {suggestions.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 px-2">
              {suggestions.map((cat) => (
                <SuggestionCard key={cat.key} category={cat} onSelect={(q) => { setQuestion(q); handleSubmit(q); }} />
              ))}
            </div>
          ) : connections.length > 0 ? (
            <div className="text-center text-xs text-slate-500 mt-4">Type any question to get started</div>
          ) : (
            <div className="text-center mt-8">
              <Database className="h-8 w-8 text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-400">Add a database connection first</p>
            </div>
          )}
        </div>
      )}

      {/* ── Results Area ── */}
      {!showWelcome && (
        <div className="flex-1 min-h-0 flex flex-col">
          {/* Row 2: Turn Nav + Metadata */}
          <div className="shrink-0 flex items-center justify-between gap-2 mb-1">
            <div className="flex items-center gap-1 overflow-x-auto no-scrollbar">
              {chatHistory.length > 1 && (
                <>
                  <button onClick={() => setActiveIdx(Math.max(0, activeIdx - 1))} disabled={activeIdx === 0}
                    className="p-0.5 text-slate-500 hover:text-slate-300 disabled:opacity-20"><ChevronLeft className="h-3 w-3" /></button>
                  {chatHistory.map((e, i) => (
                    <button key={i} onClick={() => { setActiveIdx(i); setActiveTab("table"); }}
                      className={cn("shrink-0 px-2 py-0.5 rounded text-[10px] font-medium transition-all truncate max-w-[100px]",
                        i === activeIdx ? "bg-blue-600/20 text-blue-300 border border-blue-500/30" : "text-slate-500 hover:text-slate-300")}>
                      Q{i + 1}
                    </button>
                  ))}
                  <button onClick={() => setActiveIdx(Math.min(chatHistory.length - 1, activeIdx + 1))}
                    disabled={activeIdx === chatHistory.length - 1}
                    className="p-0.5 text-slate-500 hover:text-slate-300 disabled:opacity-20"><ChevronRight className="h-3 w-3" /></button>
                  {activeIdx !== chatHistory.length - 1 && (
                    <button onClick={() => setActiveIdx(chatHistory.length - 1)}
                      className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-600/30 text-blue-300 hover:bg-blue-600/50 ml-1">Latest</button>
                  )}
                </>
              )}
            </div>

            {activeResult && (
              <div className="shrink-0 flex items-center gap-3 text-[10px] text-slate-500">
                <span><Table2 className="h-2.5 w-2.5 inline mr-0.5" />{activeResult.row_count}r</span>
                <span><Clock className="h-2.5 w-2.5 inline mr-0.5" />{activeResult.duration_ms}ms</span>
                <span className="text-slate-600">{activeResult.model}</span>
              </div>
            )}
          </div>

          {/* Loading / Error */}
          {queryMutation.isPending && (
            <div className="shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/40 mb-2">
              <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />
              <span className="text-xs text-slate-500">Generating SQL and querying database…</span>
            </div>
          )}
          {queryMutation.error && !queryMutation.isPending && (
            <Alert variant="error" className="shrink-0 mb-2">{(queryMutation.error as ApiRequestError)?.message ?? "Query failed"}</Alert>
          )}

          {/* Row 3: Tabs + Actions */}
          {activeResult && !queryMutation.isPending && (
            <>
              <div className="shrink-0 flex items-center justify-between border-b border-slate-700/40">
                <div className="flex">
                  {([
                    { id: "table" as TabId, label: "Table", icon: <Table2 className="h-3 w-3" /> },
                    { id: "chart" as TabId, label: "Chart", icon: <BarChart3 className="h-3 w-3" /> },
                    { id: "studio" as TabId, label: "Studio", icon: <Palette className="h-3 w-3" /> },
                    { id: "sql" as TabId, label: "SQL", icon: <Code2 className="h-3 w-3" /> },
                  ]).map((tab) => (
                    <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                      className={cn("flex items-center gap-1 px-3 py-2 text-[11px] font-medium border-b-2 -mb-px transition-all",
                        activeTab === tab.id ? "border-blue-500 text-blue-400" : "border-transparent text-slate-500 hover:text-slate-300")}>
                      {tab.icon}{tab.label}
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-1">
                  {activeTab === "sql" && <CopyButton text={activeResult.sql} />}

                  <button onClick={() => setShowSaveModal(true)}
                    className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors">
                    <Bookmark className="h-3 w-3" />Save
                  </button>

                  {/* Export dropdown */}
                  <div className="relative">
                    <button onClick={() => setShowExportMenu(!showExportMenu)}
                      className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors">
                      <Download className="h-3 w-3" />Export
                    </button>
                    {showExportMenu && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setShowExportMenu(false)} />
                        <div className="absolute right-0 top-full mt-1 z-20 bg-slate-800 border border-slate-700/60 rounded-lg shadow-xl py-1 min-w-[120px]">
                          {(["csv", "excel", "pdf"] as const).map((fmt) => (
                            <button key={fmt} onClick={async () => { setShowExportMenu(false); setExporting(fmt); await handleExport(fmt, activeResult); setExporting(null); }}
                              disabled={exporting !== null}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50 disabled:opacity-40">
                              {exporting === fmt ? <Loader2 className="h-3 w-3 animate-spin" /> :
                                fmt === "csv" ? <Download className="h-3 w-3" /> : fmt === "excel" ? <FileSpreadsheet className="h-3 w-3" /> : <FileText className="h-3 w-3" />}
                              {fmt.toUpperCase()}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>

                  <button onClick={() => setExpanded(!expanded)}
                    className="p-1.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors" title={expanded ? "Minimize" : "Maximize"}>
                    {expanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
                  </button>
                </div>
              </div>

              {/* Row 4: FULL CONTENT — takes all remaining space */}
              <div className="flex-1 min-h-0 overflow-hidden border border-slate-700/30 border-t-0 rounded-b-lg bg-slate-800/20">
                {activeTab === "table" && <ResultsTable columns={activeResult.columns} rows={activeResult.rows} />}
                {activeTab === "chart" && (
                  <div className="p-4 h-full overflow-y-auto">
                    <AutoChart columns={activeResult.columns} rows={activeResult.rows} fillContainer />
                  </div>
                )}
                {activeTab === "studio" && (
                  <ChartStudio columns={activeResult.columns} rows={activeResult.rows} connectionId={selectedConnection} />
                )}
                {activeTab === "sql" && (
                  <div className="h-full bg-[#1e1e1e] relative">
                    <Editor height="100%" defaultLanguage="sql" value={activeResult.sql} theme="vs-dark"
                      loading={
                        <div className="flex items-center justify-center h-full bg-[#1e1e1e]">
                          <Loader2 className="h-5 w-5 text-slate-500 animate-spin" />
                        </div>
                      }
                      options={{
                        readOnly: false, minimap: { enabled: false }, fontSize: 13, lineNumbers: "on",
                        scrollBeyondLastLine: false, wordWrap: "on", padding: { top: 12, bottom: 12 },
                        renderLineHighlight: "gutter", overviewRulerBorder: false,
                        scrollbar: { vertical: "auto", horizontal: "auto" },
                        cursorStyle: "line", cursorBlinking: "smooth",
                      }}
                    />
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Save Modal */}
      {showSaveModal && activeResult && (
        <SaveQueryModal result={activeResult} connectionId={selectedConnection} onClose={() => setShowSaveModal(false)} />
      )}
    </div>
  );
}
