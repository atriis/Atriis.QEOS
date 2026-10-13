import { apiFetch } from "./http";

// Types mirror platforms/ingestion-service/src/ingestion/schemas/api_key.py

export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  /** May read the project's test suggestions (POST /collect/impact); owners and admins set it. Older servers omit it. */
  can_read_impact?: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

// The only response that ever carries the full key
export interface ApiKeyCreated extends Omit<ApiKey, "last_used_at" | "revoked_at"> {
  key: string;
}

export function listKeys(projectId: number): Promise<ApiKey[]> {
  return apiFetch(`/api/v1/projects/${projectId}/api-keys`);
}

export function createKey(projectId: number, name: string, canReadImpact = false): Promise<ApiKeyCreated> {
  return apiFetch(`/api/v1/projects/${projectId}/api-keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, can_read_impact: canReadImpact }),
  });
}

/** Allow or stop the key's reading of test suggestions (owners and admins); a revoked key answers 409. */
export function updateKey(projectId: number, keyId: number, canReadImpact: boolean): Promise<ApiKey> {
  return apiFetch(`/api/v1/projects/${projectId}/api-keys/${keyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ can_read_impact: canReadImpact }),
  });
}

export function revokeKey(projectId: number, keyId: number): Promise<void> {
  return apiFetch(`/api/v1/projects/${projectId}/api-keys/${keyId}`, { method: "DELETE" });
}
