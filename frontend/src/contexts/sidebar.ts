/**
 * Sidebar context — extracted to its own module to prevent circular
 * dependency / TDZ crash between AppShell (main bundle) and StudioPage
 * (lazy chunk). Both import from here; neither imports from the other.
 */
import { createContext, useContext } from "react";

export interface SidebarContextType {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
}

export const SidebarContext = createContext<SidebarContextType>({
  collapsed: false,
  setCollapsed: () => {},
});

export const useSidebar = () => useContext(SidebarContext);