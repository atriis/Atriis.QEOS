import { apiFetch, buildQuery } from "./http";

// Mirrors platforms/test-management-service/src/casebook/schemas/ci.py

export interface CiTargetChange { action: "created" | "updated" | "token_replaced" | "deleted"; user_id: number; at: string }

export interface CiTarget {
  /** False when the server has no TM_SECRETS_KEY: nothing can be configured. */
  available: boolean;
  configured: boolean;
  provider: string | null;
  repo: string | null;
  workflow: string | null;
  ref: string | null;
  token_last4: string | null;
  token_expires_at: string | null;
  updated_at: string | null;
  last_change: CiTargetChange | null;
}

export interface CiTargetInput {
  repo: string;
  workflow: string;
  ref: string;
  /** Only when setting or replacing it; without it the stored token is kept. */
  token?: string;
}

export type RunRequestStatus = "queued" | "running" | "completed" | "cancelling" | "cancelled" | "failed_to_start";

export interface SelectedCase { case_number: number; path: string; name: string }

export interface RunRequest {
  id: number;
  requested_by: number;
  requested_at: string;
  selection: SelectedCase[];
  case_count: number;
  suite_id: number | null;
  /** The workflow file dispatched: a repository suite's, else the CI target's. Older servers omit it. */
  workflow?: string | null;
  status: RunRequestStatus;
  conclusion: string | null;
  github_run_id: number | null;
  github_run_url: string | null;
  stopped_by: number | null;
  stopped_at: string | null;
  error: string | null;
  checked_at: string | null;
  /** Manual cases a whole-suite run left out (they have no automated test). */
  skipped_manual: number;
  /** What the dashboard estimated before Play (ingestion's duration estimate); null for older requests. */
  estimate_ms: number | null;
  estimate_upper_ms: number | null;
  /** True while the server still checks GitHub for this request: keep polling. */
  refreshing: boolean;
}

/** A repository suite id, or a whole workflow by its file name ("suite-flights.yml"), dispatches that workflow. */
export type RunSelection = { case_numbers: number[] } | { suite_id: number } | { workflow_group: string };

export const MAX_RUN_CASES = 200;
export const EXPIRY_WARNING_DAYS = 14;
const DAY_MS = 86_400_000;
const base = (projectId: number) => `/api/v1/projects/${projectId}`;

export function isActive(r: RunRequest): boolean {
  return r.status === "queued" || r.status === "running" || r.status === "cancelling";
}

/** "expiring" from EXPIRY_WARNING_DAYS before token_expires_at; a token without expiry is always "ok". */
export function tokenState(target: CiTarget, now: number = Date.now()): "ok" | "expiring" | "expired" {
  if (!target.token_expires_at) return "ok";
  const expires = Date.parse(target.token_expires_at);
  if (expires <= now) return "expired";
  return expires - now <= EXPIRY_WARNING_DAYS * DAY_MS ? "expiring" : "ok";
}

/** "12 Mar 2027", read in UTC so the day never shifts with the viewer's time zone. */
export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(iso));
}

export function getCiTarget(projectId: number): Promise<CiTarget> {
  return apiFetch(`${base(projectId)}/ci-target`);
}

export function saveCiTarget(projectId: number, body: CiTargetInput): Promise<CiTarget> {
  return apiFetch(`${base(projectId)}/ci-target`, { method: "PUT", body: JSON.stringify(body) });
}

export function deleteCiTarget(projectId: number): Promise<void> {
  return apiFetch(`${base(projectId)}/ci-target`, { method: "DELETE" });
}

export interface RunEstimate { estimate_ms: number; estimate_upper_ms: number }

/** The estimate is sent only when known; test-management stores it as given. */
export function createRunRequest(projectId: number, selection: RunSelection, estimate?: RunEstimate | null): Promise<RunRequest> {
  return apiFetch(`${base(projectId)}/run-requests`, { method: "POST", body: JSON.stringify(estimate ? { ...selection, ...estimate } : selection) });
}

export function listRunRequests(projectId: number, q: { limit: number; offset: number }): Promise<{ total: number; items: RunRequest[] }> {
  return apiFetch(`${base(projectId)}/run-requests${buildQuery(q)}`);
}

export function getRunRequest(projectId: number, requestId: number): Promise<RunRequest> {
  return apiFetch(`${base(projectId)}/run-requests/${requestId}`);
}

export function stopRunRequest(projectId: number, requestId: number): Promise<RunRequest> {
  return apiFetch(`${base(projectId)}/run-requests/${requestId}/stop`, { method: "POST", body: "{}" });
}

/** The GitHub run URLs of Play requests made since `since` (ISO), newest first: the report's origin filter. */
export function getRunUrls(
  projectId: number,
  since: string,
  init: { signal?: AbortSignal } = {},
): Promise<{ urls: string[]; truncated: boolean }> {
  return apiFetch(`${base(projectId)}/run-requests/run-urls${buildQuery({ since })}`, init);
}
