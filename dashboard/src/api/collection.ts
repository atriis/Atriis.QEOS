import { apiFetch } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/collection_settings.py

export interface CollectionSettings {
  collect_manual: boolean;
  discarded_count: number;
  last_discarded_at: string | null;
  updated_at: string | null;
  updated_by: number | null;
}

const base = (projectId: number) => `/api/v1/projects/${projectId}/collection-settings`;

export function getCollectionSettings(projectId: number): Promise<CollectionSettings> {
  return apiFetch(base(projectId));
}

export function putCollectionSettings(projectId: number, collectManual: boolean): Promise<CollectionSettings> {
  return apiFetch(base(projectId), { method: "PUT", body: JSON.stringify({ collect_manual: collectManual }) });
}
