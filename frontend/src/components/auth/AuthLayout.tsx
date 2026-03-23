import React from "react";

interface AuthLayoutProps {
  children: React.ReactNode;
}

/**
 * Centered layout with subtle animated background for auth pages.
 * Provides the Smart BI Agent branding bar at the top.
 */
export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* Background texture */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-1/2 -right-1/2 w-full h-full bg-gradient-to-bl from-blue-600/5 via-transparent to-transparent rounded-full" />
        <div className="absolute -bottom-1/2 -left-1/2 w-full h-full bg-gradient-to-tr from-indigo-600/5 via-transparent to-transparent rounded-full" />
      </div>

      {/* Content */}
      <div className="relative z-10 flex flex-1 flex-col items-center justify-center px-4 py-8">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600/15 border border-blue-500/10 mb-4">
            <svg
              className="w-7 h-7 text-blue-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"
              />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-white tracking-tight">
            Smart BI Agent
          </h1>
          <p className="text-slate-500 text-xs mt-1">v3.1.0</p>
        </div>

        {/* Page content (Card) */}
        {children}

        {/* Footer */}
        <p className="mt-8 text-xs text-slate-600">
          &copy; 2026 Vibho Technologies / IDT
        </p>
      </div>
    </div>
  );
}
