/**
 * Smart BI Agent — DataPanel
 * Schema browser sidebar with collapsible table tree.
 * Columns are draggable into FieldWells.
 */

import { useState } from "react";
import {
  Database, Table2, Loader2, Search,
  PanelLeftClose, PanelLeftOpen, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DragCol } from "./FieldWell";
import type { SchemaTable } from "../hooks/useDashboardState";

// ─── Schema Table Tree ───────────────────────────────────────────────────────

function SchemaTree({
  tableName,
  columns,
  open: init,
}: {
  tableName: string;
  columns: { name: string; type: "numeric" | "text" | "date" }[];
  open?: boolean;
}) {
  const [open, setOpen] = useState(init || false);
  return (
    <div className="mb-0.5">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-700/20 transition-colors duration-150 text-left group"
      >
        <span
          className="text-slate-600 shrink-0 transition-transform duration-200"
          style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
        >
          <ChevronRight className="h-3 w-3" />
        </span>
        <Table2 className="h-3 w-3 text-blue-400/60 shrink-0" />
        <span className="text-[11px] font-medium text-slate-400 group-hover:text-slate-200 truncate transition-colors">
          {tableName}
        </span>
        <span className="text-[9px] text-slate-600 ml-auto shrink-0">{columns.length}</span>
      </button>
      <div
        className={cn(
          "ml-4 pl-2 border-l border-slate-800/60 space-y-0 overflow-hidden transition-all duration-300",
          open ? "max-h-[800px] opacity-100 mt-0.5" : "max-h-0 opacity-0"
        )}
      >
        {columns.map((c) => (
          <DragCol key={c.name} name={c.name} type={c.type} table={tableName} />
        ))}
      </div>
    </div>
  );
}

// ─── DataPanel ───────────────────────────────────────────────────────────────

interface DataPanelProps {
  tables: SchemaTable[];
  loading: boolean;
  hasConnection: boolean;
  schemaSearch: string;
  onSearchChange: (v: string) => void;
}

export function DataPanel({
  tables,
  loading,
  hasConnection,
  schemaSearch,
  onSearchChange,
}: DataPanelProps) {
  const [open, setOpen] = useState(true);

  const filtered = schemaSearch
    ? tables.filter((t) => {
        const q = schemaSearch.toLowerCase();
        return (
          t.name.toLowerCase().includes(q) ||
          t.columns.some((c) => c.name.toLowerCase().includes(q))
        );
      })
    : tables;

  return (
    <div
      className={cn(
        "shrink-0 border-r border-slate-700/25 bg-slate-900/40 flex flex-col",
        "transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
        open ? "w-56" : "w-10"
      )}
    >
      {/* Toggle */}
      <button
        onClick={() => setOpen(!open)}
        className="shrink-0 flex items-center justify-center gap-1.5 py-2.5 border-b border-slate-700/25 text-slate-500 hover:text-slate-300 hover:bg-slate-700/20 transition-colors duration-200"
      >
        {open ? (
          <>
            <PanelLeftClose className="h-3.5 w-3.5" />
            <span className="text-[10px] font-medium">Data</span>
          </>
        ) : (
          <PanelLeftOpen className="h-3.5 w-3.5" />
        )}
      </button>

      {open && (
        <>
          {/* Search */}
          <div className="p-2.5 border-b border-slate-700/25">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-slate-600" />
              <input
                value={schemaSearch}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search tables…"
                className="w-full h-8 rounded-lg border border-slate-700/30 bg-slate-800/30 text-[11px] text-slate-300 pl-7 pr-2.5 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/20 transition-all duration-200"
              />
            </div>
          </div>

          {/* Tree */}
          <div className="flex-1 overflow-y-auto p-2 min-h-0">
            {loading && (
              <div className="flex items-center gap-2 p-3">
                <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />
                <span className="text-[11px] text-slate-500">Loading schema…</span>
              </div>
            )}

            {!loading && filtered.length === 0 && (
              <div className="text-center p-4">
                <Database className="h-5 w-5 text-slate-700 mx-auto mb-2" />
                <p className="text-[11px] text-slate-600">
                  {hasConnection ? "No tables found" : "Select a connection"}
                </p>
              </div>
            )}

            {filtered.map((t, i) => (
              <SchemaTree
                key={t.name}
                tableName={t.name}
                columns={t.columns}
                open={i === 0 && filtered.length <= 5}
              />
            ))}
          </div>

          {/* Footer hint */}
          <div className="shrink-0 px-2.5 py-2 border-t border-slate-700/25">
            <p className="text-[9px] text-slate-600 text-center">
              Drag columns → Field wells in Properties
            </p>
          </div>
        </>
      )}
    </div>
  );
}
