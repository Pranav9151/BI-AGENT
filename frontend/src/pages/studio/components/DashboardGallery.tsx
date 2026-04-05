/**
 * Smart BI Agent — DashboardGallery
 * Horizontal tab bar for switching between saved dashboards.
 */

import { FolderOpen, PlusCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface GalleryItem {
  id: string;
  name: string;
  updated: string;
}

interface DashboardGalleryProps {
  dashboards: GalleryItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
}

export function DashboardGallery({
  dashboards,
  activeId,
  onSelect,
  onCreate,
  onDelete,
}: DashboardGalleryProps) {
  if (dashboards.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
      {dashboards.map((d) => (
        <div key={d.id} className="group relative shrink-0">
          <button
            onClick={() => onSelect(d.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-200 whitespace-nowrap",
              activeId === d.id
                ? "bg-blue-600/20 text-blue-300 border border-blue-500/25"
                : "text-slate-500 hover:text-slate-300 border border-transparent hover:border-slate-700/40"
            )}
          >
            <FolderOpen className="h-3 w-3" />
            {d.name}
          </button>
          {activeId !== d.id && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(d.id);
              }}
              className="absolute -top-1 -right-1 hidden group-hover:flex w-4 h-4 items-center justify-center rounded-full bg-red-600/80 text-white transition-opacity"
            >
              <X className="h-2 w-2" />
            </button>
          )}
        </div>
      ))}
      <button
        onClick={onCreate}
        className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] text-slate-600 hover:text-slate-400 border border-dashed border-slate-700/30 hover:border-slate-600/40 transition-all duration-200"
      >
        <PlusCircle className="h-3 w-3" /> New
      </button>
    </div>
  );
}
