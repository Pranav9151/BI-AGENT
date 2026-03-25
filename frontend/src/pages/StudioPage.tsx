/**
 * Smart BI Agent — Studio Page (Standalone)
 * Phase 7 | Placeholder — full build in Session 12
 *
 * This will become the Power BI / Looker Studio experience:
 *   - Full-screen canvas for dashboard building
 *   - Drag-and-drop widgets (charts, KPIs, tables)
 *   - Connect to any saved query or write custom SQL
 *   - Save/load/share dashboards
 *   - Export dashboards as PDF/PPT
 */

import { useNavigate } from "react-router-dom";
import {
  Palette, BarChart3, Table2, Hash, PieChart,
  LineChart, LayoutGrid, ArrowRight, Sparkles,
} from "lucide-react";
import { Button, Card } from "@/components/ui";

export default function StudioPage() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-8rem)] max-w-2xl mx-auto text-center px-4">
      {/* Hero */}
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-500/20 to-blue-500/10 border border-violet-500/15 flex items-center justify-center mb-5">
        <Palette className="h-8 w-8 text-violet-400" />
      </div>

      <h1 className="text-2xl font-bold text-white mb-2">Dashboard Studio</h1>
      <p className="text-sm text-slate-400 max-w-md mb-8">
        Build custom dashboards with drag-and-drop widgets, connect to your saved queries,
        and share analytics across your team — just like Power BI and Looker Studio.
      </p>

      {/* Feature Preview Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 w-full mb-8">
        {[
          { icon: <BarChart3 className="h-5 w-5" />, label: "Charts", color: "text-blue-400 bg-blue-500/10" },
          { icon: <Hash className="h-5 w-5" />, label: "KPI Cards", color: "text-emerald-400 bg-emerald-500/10" },
          { icon: <Table2 className="h-5 w-5" />, label: "Data Tables", color: "text-amber-400 bg-amber-500/10" },
          { icon: <LayoutGrid className="h-5 w-5" />, label: "Layouts", color: "text-violet-400 bg-violet-500/10" },
        ].map((f) => (
          <div key={f.label} className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-700/30 bg-slate-800/20">
            <span className={`p-2 rounded-lg ${f.color}`}>{f.icon}</span>
            <span className="text-xs text-slate-400">{f.label}</span>
          </div>
        ))}
      </div>

      {/* Status */}
      <Card className="p-5 w-full mb-6">
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-amber-400 shrink-0" />
          <div className="text-left">
            <p className="text-sm font-medium text-slate-200">Coming in Final Release</p>
            <p className="text-xs text-slate-500 mt-0.5">
              Dashboard Studio is being built as part of the production hardening phase.
              In the meantime, use the Chart tab in AI Query for quick visualizations.
            </p>
          </div>
        </div>
      </Card>

      {/* Quick Actions */}
      <div className="flex gap-3">
        <Button variant="primary" icon={<ArrowRight className="h-4 w-4" />} onClick={() => navigate("/query")}>
          Go to AI Query
        </Button>
        <Button variant="secondary" onClick={() => navigate("/saved-queries")}>
          Saved Queries
        </Button>
      </div>
    </div>
  );
}