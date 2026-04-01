/**
 * Smart BI Agent — Auth Layout v2 (Phase 11)
 * World-class login experience with animated data visualization background.
 * Makes Power BI's generic Microsoft login look pedestrian.
 */
import React from "react";

interface AuthLayoutProps {
  children: React.ReactNode;
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="min-h-screen bg-slate-950 flex">
      {/* ── Left: Animated Showcase ── */}
      <div className="hidden lg:flex lg:w-1/2 xl:w-[55%] relative overflow-hidden">
        {/* Mesh gradient background */}
        <div className="absolute inset-0">
          <div className="absolute inset-0 bg-gradient-to-br from-blue-950/80 via-slate-950 to-violet-950/60" />
          <div className="absolute top-1/4 -left-20 w-96 h-96 bg-blue-500/8 rounded-full blur-3xl" />
          <div className="absolute bottom-1/4 right-0 w-80 h-80 bg-violet-500/8 rounded-full blur-3xl" />
          <div className="absolute top-1/2 left-1/3 w-64 h-64 bg-emerald-500/5 rounded-full blur-3xl" />
        </div>

        {/* Animated chart lines */}
        <svg className="absolute inset-0 w-full h-full opacity-[0.06]" viewBox="0 0 800 600" preserveAspectRatio="none">
          <path d="M0 400 Q100 350 200 380 T400 320 T600 340 T800 280" fill="none" stroke="#3b82f6" strokeWidth="2">
            <animate attributeName="d" values="M0 400 Q100 350 200 380 T400 320 T600 340 T800 280;M0 380 Q100 320 200 350 T400 300 T600 360 T800 310;M0 400 Q100 350 200 380 T400 320 T600 340 T800 280" dur="8s" repeatCount="indefinite" />
          </path>
          <path d="M0 450 Q150 420 300 440 T500 400 T700 420 T800 380" fill="none" stroke="#8b5cf6" strokeWidth="1.5">
            <animate attributeName="d" values="M0 450 Q150 420 300 440 T500 400 T700 420 T800 380;M0 440 Q150 400 300 420 T500 380 T700 440 T800 400;M0 450 Q150 420 300 440 T500 400 T700 420 T800 380" dur="10s" repeatCount="indefinite" />
          </path>
          <path d="M0 500 Q200 480 350 490 T550 460 T750 470 T800 440" fill="none" stroke="#10b981" strokeWidth="1">
            <animate attributeName="d" values="M0 500 Q200 480 350 490 T550 460 T750 470 T800 440;M0 490 Q200 460 350 480 T550 440 T750 480 T800 460;M0 500 Q200 480 350 490 T550 460 T750 470 T800 440" dur="12s" repeatCount="indefinite" />
          </path>
          {/* Floating bar chart silhouette */}
          {[120, 200, 280, 360, 440, 520, 600].map((x, i) => {
            const h = [140, 200, 100, 240, 160, 180, 120][i];
            return (
              <rect key={x} x={x} y={250 - h / 2} width="40" height={h} rx="4" fill="#3b82f6" opacity="0.04">
                <animate attributeName="height" values={`${h};${h * 1.2};${h}`} dur={`${3 + i * 0.5}s`} repeatCount="indefinite" />
                <animate attributeName="y" values={`${250 - h / 2};${250 - (h * 1.2) / 2};${250 - h / 2}`} dur={`${3 + i * 0.5}s`} repeatCount="indefinite" />
              </rect>
            );
          })}
        </svg>

        {/* Content overlay */}
        <div className="relative z-10 flex flex-col justify-between p-12 xl:p-16">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-xl bg-blue-500/15 border border-blue-500/10 flex items-center justify-center">
                <svg className="w-5 h-5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
                </svg>
              </div>
              <span className="text-sm font-semibold text-slate-400">Smart BI Agent</span>
            </div>
          </div>

          <div className="max-w-md">
            <h2 className="text-3xl xl:text-4xl font-bold text-white leading-tight mb-4">
              Ask your data
              <br />
              <span className="text-gradient">anything.</span>
            </h2>
            <p className="text-slate-400 text-sm leading-relaxed mb-8">
              The AI-powered BI platform that turns natural language into insights.
              No DAX. No LookML. No learning curve. Just answers.
            </p>

            {/* Feature pills */}
            <div className="flex flex-wrap gap-2">
              {[
                "Natural Language SQL",
                "15 Chart Types",
                "AI Dashboard Builder",
                "Cross-Widget Filtering",
                "Self-Hosted",
              ].map((f) => (
                <span key={f} className="px-3 py-1.5 rounded-full text-[11px] font-medium text-slate-400 border border-slate-700/30 bg-slate-800/20">
                  {f}
                </span>
              ))}
            </div>
          </div>

          <p className="text-[10px] text-slate-700">
            &copy; 2026 Vibho Technologies / IDT
          </p>
        </div>
      </div>

      {/* ── Right: Auth Form ── */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 relative">
        {/* Mobile-only background */}
        <div className="absolute inset-0 lg:hidden">
          <div className="absolute top-1/4 -right-20 w-72 h-72 bg-blue-500/5 rounded-full blur-3xl" />
          <div className="absolute bottom-1/4 -left-20 w-72 h-72 bg-violet-500/5 rounded-full blur-3xl" />
        </div>

        {/* Mobile logo */}
        <div className="relative z-10 mb-8 text-center lg:hidden">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600/15 border border-blue-500/10 mb-4">
            <svg className="w-7 h-7 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-white">Smart BI Agent</h1>
          <p className="text-slate-500 text-xs mt-1">v3.2.0</p>
        </div>

        <div className="relative z-10 w-full max-w-sm">
          {children}
        </div>

        <p className="relative z-10 mt-8 text-[10px] text-slate-700 lg:hidden">
          &copy; 2026 Vibho Technologies / IDT
        </p>
      </div>
    </div>
  );
}
