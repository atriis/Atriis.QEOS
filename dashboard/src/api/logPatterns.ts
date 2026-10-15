import { apiFetch } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/log_pattern.py (ADR-032)

export interface LogPattern {
  id: number;
  name: string;
  pattern: string;
  link_template: string | null;
  created_at: string | null;
}

export interface LogScan {
  state: "idle" | "running";
  since: string | null;
}

export interface LogPatternList {
  patterns: LogPattern[];
  scan: LogScan;
}

export interface LogPatternInput {
  name: string;
  pattern: string;
  link_template: string | null;
}

const base = (projectId: number) => `/api/v1/projects/${projectId}/log-patterns`;

/** The project's patterns (name order) and whether past runs are being scanned. */
export function listLogPatterns(projectId: number): Promise<LogPatternList> {
  return apiFetch(base(projectId));
}

/** 422/409 carry `{code, message}`: `ApiError.code` names the field (name, pattern, link_template) or `limit`. */
export function addLogPattern(projectId: number, input: LogPatternInput): Promise<LogPattern> {
  return apiFetch(base(projectId), { method: "POST", body: JSON.stringify(input) });
}

/** The sample as it would be stored (masked) and the values this pattern finds in it; nothing is saved. */
export function previewLogPattern(
  projectId: number,
  name: string,
  pattern: string,
  sample: string,
): Promise<{ masked: string; values: string[] }> {
  return apiFetch(`${base(projectId)}/preview`, { method: "POST", body: JSON.stringify({ name, pattern, sample }) });
}

export function removeLogPattern(projectId: number, patternId: number): Promise<void> {
  return apiFetch(`${base(projectId)}/${patternId}`, { method: "DELETE" });
}
