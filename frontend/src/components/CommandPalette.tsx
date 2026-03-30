/**
 * Smart BI Agent — Command Palette (Phase 9)
 * Ctrl+K global search & navigate — like VS Code / Linear / Notion
 */
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search, LayoutDashboard, MessageSquare, Bookmark, HardDrive,
  Palette, Database, Brain, Bell, Clock, Shield, Activity,
  Users, User, BarChart3, Settings2, ArrowRight, Command,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: React.ReactNode;
  path: string;
  keywords: string[];
  adminOnly?: boolean;
}

const COMMANDS: CommandItem[] = [
  { id: "dashboard", label: "Dashboard", description: "Home & stats overview", icon: <LayoutDashboard className="h-4 w-4" />, path: "/", keywords: ["home", "dashboard", "overview", "stats"] },
  { id: "query", label: "AI Query", description: "Ask questions in plain English", icon: <MessageSquare className="h-4 w-4" />, path: "/query", keywords: ["query", "ask", "question", "ai", "sql", "natural language"] },
  { id: "saved", label: "Saved Queries", description: "Your query library", icon: <Bookmark className="h-4 w-4" />, path: "/saved-queries", keywords: ["saved", "queries", "library", "bookmarks"] },
  { id: "schema", label: "Schema Browser", description: "Explore tables & columns", icon: <HardDrive className="h-4 w-4" />, path: "/schema-browser", keywords: ["schema", "browser", "tables", "columns", "database", "explore"] },
  { id: "studio", label: "Dashboard Studio", description: "Build Power BI-style dashboards", icon: <Palette className="h-4 w-4" />, path: "/studio", keywords: ["studio", "canvas", "dashboard", "builder", "powerbi", "charts", "visual"] },
  { id: "connections", label: "Connections", description: "Database connections", icon: <Database className="h-4 w-4" />, path: "/connections", keywords: ["connections", "database", "postgres", "mysql", "bigquery"], adminOnly: true },
  { id: "llm", label: "LLM Providers", description: "AI model management", icon: <Brain className="h-4 w-4" />, path: "/llm-providers", keywords: ["llm", "providers", "ai", "model", "openai", "groq"], adminOnly: true },
  { id: "notifications", label: "Notifications", description: "Slack, Email, Teams setup", icon: <Bell className="h-4 w-4" />, path: "/notifications", keywords: ["notifications", "slack", "email", "teams", "alerts"], adminOnly: true },
  { id: "schedules", label: "Schedules", description: "Automated report scheduling", icon: <Clock className="h-4 w-4" />, path: "/schedules", keywords: ["schedules", "cron", "automation", "reports"], adminOnly: true },
  { id: "permissions", label: "Permissions", description: "RBAC access control", icon: <Shield className="h-4 w-4" />, path: "/admin/permissions", keywords: ["permissions", "rbac", "access", "roles", "security"], adminOnly: true },
  { id: "monitoring", label: "Monitoring", description: "Health, audit & tokens", icon: <Activity className="h-4 w-4" />, path: "/monitoring", keywords: ["monitoring", "health", "audit", "logs", "tokens"], adminOnly: true },
  { id: "admin", label: "User Admin", description: "Manage user accounts", icon: <Users className="h-4 w-4" />, path: "/admin", keywords: ["admin", "users", "accounts", "manage"], adminOnly: true },
  { id: "profile", label: "Profile", description: "Your account settings", icon: <User className="h-4 w-4" />, path: "/profile", keywords: ["profile", "account", "settings", "password"] },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "admin";

  // Keyboard shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        setQuery("");
        setSelectedIdx(0);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  // Focus input when opened
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return COMMANDS.filter((cmd) => {
      if (cmd.adminOnly && !isAdmin) return false;
      if (!q) return true;
      return (
        cmd.label.toLowerCase().includes(q) ||
        cmd.description?.toLowerCase().includes(q) ||
        cmd.keywords.some((k) => k.includes(q))
      );
    });
  }, [query, isAdmin]);

  const handleSelect = useCallback(
    (item: CommandItem) => {
      navigate(item.path);
      setOpen(false);
      setQuery("");
    },
    [navigate]
  );

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && filtered[selectedIdx]) {
      handleSelect(filtered[selectedIdx]);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh]">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-lg animate-scale-in">
        <div className="glass-strong rounded-2xl shadow-2xl overflow-hidden">
          {/* Search Input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-700/40">
            <Search className="h-4 w-4 text-slate-500 shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => { setQuery(e.target.value); setSelectedIdx(0); }}
              onKeyDown={handleKeyDown}
              placeholder="Search pages, features…"
              className="flex-1 bg-transparent text-sm text-white placeholder:text-slate-500 focus:outline-none"
            />
            <kbd className="hidden sm:flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-slate-600/50 bg-slate-700/30 text-[9px] text-slate-500 font-mono">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div className="max-h-[50vh] overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-4 py-8 text-center">
                <Search className="h-6 w-6 text-slate-700 mx-auto mb-2" />
                <p className="text-sm text-slate-500">No results for "{query}"</p>
              </div>
            ) : (
              filtered.map((item, i) => (
                <button
                  key={item.id}
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setSelectedIdx(i)}
                  className={cn(
                    "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                    selectedIdx === i
                      ? "bg-blue-500/10 text-white"
                      : "text-slate-400 hover:bg-slate-700/20"
                  )}
                >
                  <span
                    className={cn(
                      "p-1.5 rounded-lg shrink-0 transition-colors",
                      selectedIdx === i ? "bg-blue-500/20 text-blue-400" : "bg-slate-700/30 text-slate-500"
                    )}
                  >
                    {item.icon}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{item.label}</p>
                    {item.description && (
                      <p className="text-[10px] text-slate-500 truncate">{item.description}</p>
                    )}
                  </div>
                  {selectedIdx === i && (
                    <ArrowRight className="h-3 w-3 text-blue-400 shrink-0" />
                  )}
                </button>
              ))
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-4 py-2 border-t border-slate-700/40 bg-slate-800/20">
            <div className="flex items-center gap-3 text-[9px] text-slate-600">
              <span className="flex items-center gap-1">
                <kbd className="px-1 py-0.5 rounded border border-slate-700/40 bg-slate-800/40 font-mono">↑↓</kbd>
                Navigate
              </span>
              <span className="flex items-center gap-1">
                <kbd className="px-1 py-0.5 rounded border border-slate-700/40 bg-slate-800/40 font-mono">↵</kbd>
                Open
              </span>
            </div>
            <span className="text-[9px] text-slate-600">{filtered.length} results</span>
          </div>
        </div>
      </div>
    </div>
  );
}
