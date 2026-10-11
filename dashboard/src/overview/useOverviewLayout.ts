import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type LayoutMode, type LayoutRow, type OverviewLayoutState, conflictOf, deleteLayout, getOverviewLayout, saveLayout,
} from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";

export const layoutKey = (projectId: number) => ["overview-layout", projectId] as const;

/** The state after a successful save, so the page shows it at once (a refetch follows). */
export function afterSave(old: OverviewLayoutState, mode: LayoutMode, row: LayoutRow): OverviewLayoutState {
  if (mode === "personal") {
    return { ...old, effective: row.layout, source: "personal", personal: { version: row.version, updated_at: row.updated_at } };
  }
  const project = { version: row.version, updated_by: row.updated_by, updated_at: row.updated_at, layout: row.layout };
  return old.source === "personal" ? { ...old, project } : { ...old, project, effective: row.layout, source: "project" };
}

/** The state after a reset: personal falls back to the project default, the project default to the built-in one. */
export function afterReset(old: OverviewLayoutState, mode: LayoutMode): OverviewLayoutState {
  if (mode === "personal") {
    return { ...old, personal: null, effective: old.project?.layout ?? null, source: old.project ? "project" : "builtin" };
  }
  return old.source === "personal" ? { ...old, project: null } : { ...old, project: null, effective: null, source: "builtin" };
}

export function useOverviewLayout(projectId: number) {
  const queryClient = useQueryClient();
  const key = layoutKey(projectId);
  const query = useQuery({ queryKey: key, queryFn: () => getOverviewLayout(projectId), staleTime: 60_000 });
  const apply = (next: (old: OverviewLayoutState) => OverviewLayoutState) => {
    queryClient.setQueryData<OverviewLayoutState>(key, (old) => (old ? next(old) : old));
    void queryClient.invalidateQueries({ queryKey: key });
  };
  const save = useMutation({
    mutationFn: (args: { mode: LayoutMode; layout: StoredLayout; version: number }) =>
      saveLayout(projectId, args.mode, args.layout, args.version),
    onSuccess: (row, args) => apply((old) => afterSave(old, args.mode, row)),
    // A stale save: the cached versions are behind the server, so Reload or Overwrite must start from fresh ones
    onError: (error) => {
      if (conflictOf(error) !== undefined) void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const reset = useMutation({
    mutationFn: (mode: LayoutMode) => deleteLayout(projectId, mode),
    onSuccess: (_, mode) => apply((old) => afterReset(old, mode)),
  });
  return { query, save, reset };
}
