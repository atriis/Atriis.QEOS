import { apiFetch } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/collection_settings.py

export interface CollectionSettings {
  collect_manual: boolean;
  /** Keep step screenshots from uploads (ADR-036), off by default; absent from an older server, which reads as off. */
  keep_screenshots?: boolean;
  discarded_count: number;
  last_discarded_at: string | null;
  updated_at: string | null;
  updated_by: number | null;
}

const base = (projectId: number) => `/api/v1/projects/${projectId}/collection-settings`;

export function getCollectionSettings(projectId: number): Promise<CollectionSettings> {
  return apiFetch(base(projectId));
}

/** Changes only the settings sent; the others keep their stored value. */
export function putCollectionSettings(projectId: number, change: { collect_manual?: boolean; keep_screenshots?: boolean }): Promise<CollectionSettings> {
  return apiFetch(base(projectId), { method: "PUT", body: JSON.stringify(change) });
}
