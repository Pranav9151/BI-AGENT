/**
 * Smart BI Agent — useDashboardState hook
 * Manages dashboard CRUD, gallery, snapshot URL, and connection state.
 * Extracted from StudioPage monolith for testability and maintainability.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { ConnectionListResponse } from "@/types/connections";
import type { SchemaResponse } from "@/types/schema";
import {
  type StudioDashboard,
  type CanvasWidget,
  type ColType,
  toColType,
  serializeDashboard,
  deserializeWidgets,
} from "../lib/widget-types";

export interface SchemaTable {
  name: string;
  columns: { name: string; type: ColType }[];
}

export function useDashboardState() {
  // ── Core Dashboard State ──
  const [dashboard, setDashboard] = useState<StudioDashboard>({
    id: "", title: "My Dashboard", description: "", connectionId: "",
    widgets: [], columns: 12, updatedAt: new Date().toISOString(),
  });

  const [selWidgetId, setSelWidgetId] = useState<string | null>(null);
  const [globalFilter, setGlobalFilter] = useState<{ column: string; value: string } | null>(null);

  // ── Connections ──
  const { data: connData } = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionListResponse>("/connections/"),
  });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];

  useEffect(() => {
    if (connections.length > 0 && !dashboard.connectionId) {
      setDashboard((d) => ({ ...d, connectionId: connections[0].connection_id }));
    }
  }, [connections, dashboard.connectionId]);

  // ── Schema ──
  const { data: schemaData, isLoading: schemaLoading } = useQuery({
    queryKey: ["schema", dashboard.connectionId],
    queryFn: () => api.get<SchemaResponse>(`/schema/${dashboard.connectionId}`),
    enabled: !!dashboard.connectionId,
  });

  const schemaTables = useMemo((): SchemaTable[] => {
    if (!schemaData?.schema_data) return [];
    return Object.entries(schemaData.schema_data).map(([name, info]) => ({
      name,
      columns: Object.entries(info.columns).map(([cn, ci]) => ({
        name: cn,
        type: toColType(ci.type),
      })),
    }));
  }, [schemaData]);

  // ── Dashboard Gallery (API) ──
  const { data: dashList, refetch: refetchDashboards } = useQuery({
    queryKey: ["dashboards"],
    queryFn: () => api.get<{ dashboards: any[]; total: number }>("/dashboards/"),
  });

  const allDashboards = useMemo(
    () => (dashList?.dashboards ?? []).map((d: any) => ({
      id: d.dashboard_id,
      name: d.name,
      updated: d.updated_at,
    })),
    [dashList]
  );

  // ── Load first dashboard on mount ──
  const loadedRef = useRef(false);
  useEffect(() => {
    if (loadedRef.current || !dashList?.dashboards?.length) return;
    loadedRef.current = true;

    // Check for snapshot in URL hash
    const hash = window.location.hash;
    let snapDashId: string | null = null;
    let snapFilter: { column: string; value: string } | null = null;
    if (hash.startsWith("#snap=")) {
      try {
        const state = JSON.parse(atob(hash.slice(6)));
        if (state.d) snapDashId = state.d;
        if (state.fc && state.fv) snapFilter = { column: state.fc, value: state.fv };
      } catch {}
    }

    const target = snapDashId
      ? dashList.dashboards.find((x: any) => x.dashboard_id === snapDashId) || dashList.dashboards[0]
      : dashList.dashboards[0];
    const cfg = target.config || {};
    setDashboard({
      id: target.dashboard_id,
      title: target.name || "My Dashboard",
      description: target.description || "",
      connectionId: cfg.connection_id || "",
      columns: cfg.columns || 12,
      widgets: deserializeWidgets(cfg.widgets, cfg.connection_id || ""),
      updatedAt: target.updated_at,
    });
    if (snapFilter) setGlobalFilter(snapFilter);
  }, [dashList]);

  // ── Save / Create ──
  const saveMut = useMutation({
    mutationFn: async (d: StudioDashboard) => {
      const payload = serializeDashboard(d);
      if (d.id) {
        await api.put(`/dashboards/${d.id}`, payload);
        return d.id;
      } else {
        const res = await api.post<{ dashboard_id: string }>("/dashboards/", payload);
        return res.dashboard_id;
      }
    },
    onSuccess: (id) => {
      setDashboard((d) => ({ ...d, id }));
      refetchDashboards();
      toast.success("Dashboard saved");
    },
    onError: () => toast.error("Save failed"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/${id}`),
    onSuccess: () => { refetchDashboards(); toast.success("Dashboard deleted"); },
  });

  // ── Actions ──
  const handleSave = useCallback(() => saveMut.mutate(dashboard), [dashboard, saveMut]);

  const handleShareSnapshot = useCallback(() => {
    const state: Record<string, string> = {};
    if (dashboard.id) state.d = dashboard.id;
    if (globalFilter) { state.fc = globalFilter.column; state.fv = globalFilter.value; }
    const hash = btoa(JSON.stringify(state));
    const url = `${window.location.origin}${window.location.pathname}#snap=${hash}`;
    navigator.clipboard.writeText(url);
    toast.success("Snapshot URL copied to clipboard");
  }, [dashboard.id, globalFilter]);

  const handleCreate = useCallback(() => {
    const d: StudioDashboard = {
      id: "", title: `Dashboard ${allDashboards.length + 1}`, description: "",
      connectionId: dashboard.connectionId, widgets: [], columns: 12,
      updatedAt: new Date().toISOString(),
    };
    setDashboard(d);
    setSelWidgetId(null);
    loadedRef.current = true;
    toast.success("New dashboard created — add visuals!");
  }, [allDashboards.length, dashboard.connectionId]);

  const handleLoadDashboard = useCallback((id: string) => {
    const d = dashList?.dashboards?.find((x: any) => x.dashboard_id === id);
    if (!d) return;
    const cfg = d.config || {};
    setDashboard({
      id: d.dashboard_id, title: d.name, description: d.description || "",
      connectionId: cfg.connection_id || dashboard.connectionId, columns: cfg.columns || 12,
      widgets: deserializeWidgets(cfg.widgets, cfg.connection_id || ""),
      updatedAt: d.updated_at,
    });
    setSelWidgetId(null);
    toast.success(`Loaded "${d.name}"`);
  }, [dashList, dashboard.connectionId]);

  const handleDeleteDashboard = useCallback((id: string) => {
    if (id === dashboard.id) { toast.error("Can't delete the active dashboard"); return; }
    deleteMut.mutate(id);
  }, [dashboard.id, deleteMut]);

  return {
    dashboard, setDashboard,
    selWidgetId, setSelWidgetId,
    globalFilter, setGlobalFilter,
    connections,
    schemaTables, schemaLoading,
    allDashboards,
    saveMut, handleSave, handleShareSnapshot,
    handleCreate, handleLoadDashboard, handleDeleteDashboard,
  };
}
