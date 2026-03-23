import React, { useEffect, useState } from "react";

interface HealthResponse {
  status: string;
}

type PhaseStatus = "ok" | "error" | "checking" | "pending";

interface StatusRowProps {
  label: string;
  status: PhaseStatus;
}

function StatusRow({ label, status }: StatusRowProps): React.JSX.Element {
  const config: Record<PhaseStatus, { dot: string; text: string; badge: string }> = {
    ok:       { dot: "bg-green-400",  text: "text-green-400",  badge: "Ready" },
    error:    { dot: "bg-red-400",    text: "text-red-400",    badge: "Error" },
    checking: { dot: "bg-yellow-400", text: "text-yellow-400", badge: "Checking..." },
    pending:  { dot: "bg-slate-500",  text: "text-slate-500",  badge: "Upcoming" },
  };
  const s = config[status];

  return (
    <div className="flex items-center justify-between py-2.5 px-4 rounded-lg bg-slate-700/30">
      <span className="text-slate-300 text-sm">{label}</span>
      <div className="flex items-center gap-2">
        <span className={`text-xs font-medium ${s.text}`}>{s.badge}</span>
        <span className={`w-2.5 h-2.5 rounded-full ${s.dot}`} />
      </div>
    </div>
  );
}

function App(): React.JSX.Element {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    fetch("/health")
      .then((res) => res.json())
      .then((data: HealthResponse) => setHealth(data))
      .catch(() => setError(true));
  }, []);

  const backendStatus: PhaseStatus = health ? "ok" : error ? "error" : "checking";

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="max-w-lg w-full">
        <div className="bg-slate-800 rounded-2xl shadow-2xl p-8 border border-slate-700">

          {/* Logo */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-blue-600/20 mb-4">
              <svg className="w-8 h-8 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">
              Smart BI Agent
            </h1>
            <p className="text-slate-400 mt-1 text-sm">v3.1.0 — Architecture Ready</p>
          </div>

          {/* Status rows */}
          <div className="space-y-2.5 mb-8">
            <StatusRow label="Backend API"              status={backendStatus} />
            <StatusRow label="Phase 1 — Infrastructure" status="ok" />
            <StatusRow label="Phase 2 — API Routes"     status="ok" />
            <StatusRow label="Phase 3 — IAM Frontend"   status="pending" />
          </div>

          {/* Connection info */}
          <div className="bg-slate-700/40 rounded-xl p-4 text-sm text-slate-400 leading-relaxed">
            {health?.status === "ok" ? (
              <p>
                Backend is <span className="text-green-400 font-semibold">connected</span> and
                healthy. All Phase 1 &amp; 2 components are operational. Phase 3 will
                add login UI, query editor, dashboard, and admin panels.
              </p>
            ) : error ? (
              <p>
                Backend is <span className="text-red-400 font-semibold">not reachable</span>.
                Make sure all Docker services are running:{" "}
                <code className="text-blue-400 bg-slate-800 px-1.5 py-0.5 rounded text-xs">
                  docker compose up -d
                </code>
              </p>
            ) : (
              <p>
                Connecting to backend<span className="text-yellow-400">...</span>
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="mt-6 pt-4 border-t border-slate-700/50 text-center">
            <p className="text-xs text-slate-600">
              Smart BI Agent &copy; 2026 &mdash; Vibho Technologies / IDT
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}

export default App;
