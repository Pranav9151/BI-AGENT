/**
 * Smart BI Agent — AppShell v3 (Phase 9.5)
 *
 * Fixes:
 *   - h-screen + overflow-hidden root — no content going off-screen
 *   - Smooth 300ms sidebar transition with proper flex containment
 *   - min-w-0 on main content prevents flex overflow
 *   - Command Palette (Ctrl+K) integration
 *   - Version badge updated to v3.2
 */
import { useState, createContext, useContext } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Database, Brain, MessageSquare, Bookmark,
  Users, User, LogOut, Menu, X, ChevronDown, HardDrive,
  Bell, Clock, Shield, Activity, Palette,
  PanelLeftClose, PanelLeftOpen, Search,
} from "lucide-react";

import { useAuthStore } from "@/stores/auth-store";
import { RoleGuard } from "@/components/auth";
import { cn } from "@/lib/utils";
import CommandPalette from "@/components/CommandPalette";

// ─── Sidebar Context ────────────────────────────────────────────────────────

interface SidebarContextType {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
}

const SidebarContext = createContext<SidebarContextType>({ collapsed: false, setCollapsed: () => {} });
export const useSidebar = () => useContext(SidebarContext);

// ─── Nav Items ──────────────────────────────────────────────────────────────

interface NavItem { label: string; path: string; icon: React.ReactNode; adminOnly?: boolean; }

const navItems: NavItem[] = [
  { label: "Dashboard", path: "/", icon: <LayoutDashboard className="h-4 w-4" /> },
  { label: "AI Query", path: "/query", icon: <MessageSquare className="h-4 w-4" /> },
  { label: "Saved Queries", path: "/saved-queries", icon: <Bookmark className="h-4 w-4" /> },
  { label: "Schema Browser", path: "/schema-browser", icon: <HardDrive className="h-4 w-4" /> },
  { label: "Studio", path: "/studio", icon: <Palette className="h-4 w-4" /> },
  { label: "Connections", path: "/connections", icon: <Database className="h-4 w-4" />, adminOnly: true },
  { label: "LLM Providers", path: "/llm-providers", icon: <Brain className="h-4 w-4" />, adminOnly: true },
  { label: "Notifications", path: "/notifications", icon: <Bell className="h-4 w-4" />, adminOnly: true },
  { label: "Schedules", path: "/schedules", icon: <Clock className="h-4 w-4" />, adminOnly: true },
  { label: "Permissions", path: "/admin/permissions", icon: <Shield className="h-4 w-4" />, adminOnly: true },
  { label: "Monitoring", path: "/monitoring", icon: <Activity className="h-4 w-4" />, adminOnly: true },
  { label: "Admin", path: "/admin", icon: <Users className="h-4 w-4" />, adminOnly: true },
  { label: "Profile", path: "/profile", icon: <User className="h-4 w-4" /> },
];

// ─── Sidebar Link ───────────────────────────────────────────────────────────

function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const link = (
    <NavLink
      to={item.path}
      end={item.path === "/"}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-200",
          collapsed ? "justify-center px-2 py-2.5" : "px-3 py-2",
          isActive
            ? "bg-blue-600/15 text-blue-400 border border-blue-500/15"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent"
        )
      }
      title={collapsed ? item.label : undefined}
    >
      <span className="shrink-0">{item.icon}</span>
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  );

  if (item.adminOnly) return <RoleGuard minRole="admin">{link}</RoleGuard>;
  return link;
}

// ─── Shell ──────────────────────────────────────────────────────────────────

export default function AppShell() {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const roleBadge = {
    admin: "text-amber-400 bg-amber-500/10",
    analyst: "text-blue-400 bg-blue-500/10",
    viewer: "text-slate-400 bg-slate-500/10",
  }[user?.role ?? "viewer"];

  return (
    <SidebarContext.Provider value={{ collapsed, setCollapsed }}>
      {/* ★ KEY FIX: h-screen + overflow-hidden = no content escaping */}
      <div className="h-screen overflow-hidden bg-slate-900 flex">

        {/* ── Mobile Overlay ── */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 lg:hidden transition-opacity duration-300"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* ── Sidebar ── */}
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-50 flex flex-col shrink-0",
            "bg-slate-800/95 backdrop-blur-sm border-r border-slate-700/60",
            // ★ KEY: smooth width transition
            "transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
            "lg:static lg:translate-x-0",
            sidebarOpen ? "translate-x-0" : "-translate-x-full",
            collapsed ? "lg:w-[60px]" : "lg:w-[240px]",
            "w-[240px]"
          )}
        >
          {/* Logo */}
          <div className={cn(
            "h-14 flex items-center gap-3 border-b border-slate-700/40 shrink-0 transition-all duration-300",
            collapsed ? "px-2 justify-center" : "px-4"
          )}>
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600/20 to-violet-600/10 flex items-center justify-center shrink-0">
              <svg className="w-4 h-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
              </svg>
            </div>
            {!collapsed && (
              <div className="min-w-0 overflow-hidden">
                <p className="text-sm font-semibold text-white truncate">Smart BI Agent</p>
                <p className="text-[10px] text-slate-500">v3.2.0</p>
              </div>
            )}
            <button className="ml-auto lg:hidden text-slate-400 hover:text-white transition-colors" onClick={() => setSidebarOpen(false)}>
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Collapse toggle */}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="hidden lg:flex items-center justify-center gap-2 py-2 mx-2 mt-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/30 transition-all duration-200 text-xs"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <><PanelLeftClose className="h-3.5 w-3.5" /><span>Collapse</span></>}
          </button>

          {/* Nav */}
          <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto overflow-x-hidden">
            {navItems.map((item) => (
              <SidebarLink key={item.path} item={item} collapsed={collapsed} />
            ))}
          </nav>

          {/* User */}
          <div className="border-t border-slate-700/40 p-2 shrink-0">
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen((v) => !v)}
                className={cn("w-full flex items-center gap-3 rounded-lg hover:bg-slate-700/40 transition-colors", collapsed ? "justify-center px-2 py-2" : "px-3 py-2")}
              >
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
                  {user?.name?.charAt(0)?.toUpperCase() ?? "?"}
                </div>
                {!collapsed && (
                  <>
                    <div className="text-left min-w-0 flex-1 overflow-hidden">
                      <p className="text-sm font-medium text-slate-200 truncate">{user?.name ?? "User"}</p>
                      <p className={`text-[10px] font-medium px-1.5 py-0 rounded-full inline-block ${roleBadge}`}>
                        {user?.role ?? "viewer"}
                      </p>
                    </div>
                    <ChevronDown className={cn("h-4 w-4 text-slate-500 transition-transform duration-200", userMenuOpen && "rotate-180")} />
                  </>
                )}
              </button>

              {userMenuOpen && (
                <div className={cn(
                  "absolute bottom-full mb-1 rounded-lg shadow-xl overflow-hidden border border-slate-700/60 animate-scale-in",
                  "bg-slate-800/95 backdrop-blur-md",
                  collapsed ? "left-full ml-1 w-48" : "left-0 right-0"
                )}>
                  <button onClick={() => { setUserMenuOpen(false); navigate("/profile"); }}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors">
                    <User className="h-4 w-4" />Profile
                  </button>
                  <button onClick={() => { setUserMenuOpen(false); handleLogout(); }}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-red-400 hover:bg-red-500/10 transition-colors">
                    <LogOut className="h-4 w-4" />Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* ── Main Content ── */}
        {/* ★ KEY FIX: flex-1 + min-w-0 + overflow-hidden = proper containment */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Header */}
          <header className="h-14 shrink-0 bg-slate-800/60 backdrop-blur-sm border-b border-slate-700/40 flex items-center px-4 lg:px-6">
            <button className="lg:hidden text-slate-400 hover:text-white mr-3 transition-colors" onClick={() => setSidebarOpen(true)}>
              <Menu className="h-5 w-5" />
            </button>
            <div className="flex-1" />
            <button
              onClick={() => {
                window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
              }}
              className="hidden sm:flex items-center gap-2 h-8 px-3 rounded-lg border border-slate-700/40 bg-slate-800/30 text-slate-500 hover:text-slate-300 hover:border-slate-600/50 transition-all duration-200 text-xs mr-3"
            >
              <Search className="h-3 w-3" />
              <span>Search…</span>
              <kbd className="ml-2 px-1.5 py-0.5 rounded border border-slate-700/50 bg-slate-800/50 text-[9px] font-mono text-slate-600">⌘K</kbd>
            </button>
            <p className="text-xs text-slate-500 hidden sm:block truncate max-w-[200px]">{user?.email}</p>
          </header>

          {/* ★ KEY FIX: flex-1 + overflow-y-auto HERE, not on parent */}
          <main className="flex-1 overflow-y-auto overflow-x-hidden p-4 lg:p-6">
            <Outlet />
          </main>
        </div>

        <CommandPalette />
      </div>
    </SidebarContext.Provider>
  );
}
