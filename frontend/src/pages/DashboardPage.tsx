import {
  BarChart3,
  Database,
  MessageSquare,
  Calendar,
  FileDown,
  Bell,
  Shield,
  Settings,
} from "lucide-react";

import { useAuthStore } from "@/stores/auth-store";
import { RoleGuard } from "@/components/auth";
import { Card, CardContent } from "@/components/ui";

// ─── Feature Cards ───────────────────────────────────────────────────────────

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  status: "ready" | "upcoming";
}

function FeatureCard({ icon, title, description, status }: FeatureCardProps) {
  return (
    <div className="group relative flex gap-4 p-4 rounded-xl bg-slate-800/40 border border-slate-700/40 hover:border-slate-600/60 transition-colors">
      <div className="shrink-0 w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/10 flex items-center justify-center text-blue-400 group-hover:bg-blue-500/15 transition-colors">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-slate-200">{title}</h3>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
              status === "ready"
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                : "bg-slate-500/10 text-slate-500 border border-slate-600/30"
            }`}
          >
            {status === "ready" ? "API Ready" : "Phase 4+"}
          </span>
        </div>
        <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
          {description}
        </p>
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="space-y-6">
      {/* Welcome */}
      <div>
        <h1 className="text-2xl font-bold text-white">
          Welcome back{user?.name ? `, ${user.name.split(" ")[0]}` : ""}
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Smart BI Agent v3.1.0 — Phase 4 Query + Viz complete
        </p>
      </div>

      {/* Status summary */}
      <Card>
        <CardContent className="pt-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatusBadge label="Infrastructure" phase={1} done />
            <StatusBadge label="API Routes" phase={2} done />
            <StatusBadge label="IAM Frontend" phase={3} done />
            <StatusBadge label="Query + Viz" phase={4} done />
          </div>
        </CardContent>
      </Card>

      {/* Feature grid */}
      <div>
        <h2 className="text-base font-semibold text-white mb-3">
          Platform modules
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <FeatureCard
            icon={<Database className="h-5 w-5" />}
            title="Database Connections"
            description="Connect to PostgreSQL, MySQL, BigQuery and more with encrypted credentials"
            status="ready"
          />
          <FeatureCard
            icon={<MessageSquare className="h-5 w-5" />}
            title="AI Query Engine"
            description="Natural language to SQL with multi-provider LLM support and fallback chains"
            status="ready"
          />
          <FeatureCard
            icon={<BarChart3 className="h-5 w-5" />}
            title="Visualizations"
            description="Auto-generated charts and dashboards from query results"
            status="ready"
          />
          <FeatureCard
            icon={<Calendar className="h-5 w-5" />}
            title="Scheduled Reports"
            description="Cron-based query scheduling with timezone support and distributed locks"
            status="ready"
          />
          <FeatureCard
            icon={<FileDown className="h-5 w-5" />}
            title="Export Engine"
            description="CSV, Excel, PDF exports with classification stamps and sensitivity controls"
            status="ready"
          />
          <FeatureCard
            icon={<Bell className="h-5 w-5" />}
            title="Notifications"
            description="Slack, Teams, WhatsApp, email delivery with encrypted configurations"
            status="ready"
          />
          <RoleGuard minRole="admin">
            <FeatureCard
              icon={<Shield className="h-5 w-5" />}
              title="Permissions"
              description="3-tier RBAC with role, department, and user-level overrides"
              status="ready"
            />
          </RoleGuard>
          <RoleGuard minRole="admin">
            <FeatureCard
              icon={<Settings className="h-5 w-5" />}
              title="Admin Panel"
              description="User management, LLM providers, audit log, and system configuration"
              status="ready"
            />
          </RoleGuard>
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function StatusBadge({
  label,
  phase,
  done,
}: {
  label: string;
  phase: number;
  done: boolean;
}) {
  return (
    <div className="text-center p-3 rounded-lg bg-slate-800/40">
      <div
        className={`text-xs font-bold mb-1 ${
          done ? "text-emerald-400" : "text-slate-500"
        }`}
      >
        Phase {phase}
      </div>
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1.5">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            done ? "bg-emerald-400" : "bg-slate-600"
          }`}
        />
      </div>
    </div>
  );
}
