import { apiFetch, buildQuery } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/impact.py (spec 2026-10-12 §3.5, §9)

export type ImpactKind = "statistical" | "test_file_changed" | "failing_on_branch" | "no_history";

export interface ImpactTestRef {
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
}

export interface ImpactEvidence {
  path_unit: string;
  changed_runs: number;
  new_failures: number;
  confidence: number;
  /** Null when the test never newly failed otherwise (base rate 0). */
  lift: number | null;
  base_rate: number | null;
}

export interface SuggestedTest extends ImpactTestRef {
  kind: ImpactKind;
  /** Null for the always-included kinds, which carry a label instead. */
  evidence: ImpactEvidence | null;
}

export interface ImpactSuggestion {
  state: "ok" | "not_enough_history";
  model_version: string;
  history_runs: number;
  needed_runs: number;
  /** Statistical suggestions before the cap of 50. */
  statistical_total: number;
  tests: SuggestedTest[];
}

export interface ImpactOutcome {
  evaluated_at: string;
  caught: ImpactTestRef[];
  missed: ImpactTestRef[];
}

export interface RunImpact {
  run_id: number;
  /** `no_change_data`: no changed files uploaded; `not_scored`: changed files, but no stored suggestion. */
  state: "ok" | "not_enough_history" | "no_change_data" | "not_scored";
  changed_paths: string[];
  replayed: boolean;
  scored_at: string | null;
  suggestion: ImpactSuggestion | null;
  /** Null until written, right after the upload. */
  outcome: ImpactOutcome | null;
}

export interface AccuracyPart {
  runs: number;
  caught: number;
  missed: number;
  /** Tests suggested over those runs. */
  suggested: number;
}

export interface ImpactMiss extends ImpactTestRef {
  run_id: number;
  started_at: string;
  branch: string | null;
  replayed: boolean;
}

export interface ImpactAccuracy {
  days: number;
  caught: number;
  missed: number;
  /** caught / (caught + missed); null when there were no new failures. */
  rate: number | null;
  /** Suggested tests per run counted; null when no run was evaluated. */
  avg_suggested: number | null;
  includes_replayed: boolean;
  live: AccuracyPart;
  replayed: AccuracyPart;
  /** Newest run first, at most 50; `misses_total` counts them all. */
  misses: ImpactMiss[];
  misses_total: number;
}

export type AccuracyDays = 7 | 14 | 30;

const base = (projectId: number) => `/api/v1/projects/${projectId}`;

/** The suggestion stored with a run and its outcome. */
export function getRunImpact(projectId: number, runId: number): Promise<RunImpact> {
  return apiFetch(`${base(projectId)}/runs/${runId}/impact`);
}

/** Likely affected tests for any change, as of now. A timeout is a 503 whose message the ApiError carries. */
export function scoreChange(projectId: number, changedPaths: string[], branch: string | null): Promise<ImpactSuggestion> {
  return apiFetch(`${base(projectId)}/analytics/impact`, {
    method: "POST",
    body: JSON.stringify({ changed_paths: changedPaths, branch }),
  });
}

/** How often the stored suggestions contained the new failures, over the last 7, 14 or 30 days. */
export function getImpactAccuracy(projectId: number, days: AccuracyDays, init: { signal?: AbortSignal } = {}): Promise<ImpactAccuracy> {
  return apiFetch(`${base(projectId)}/analytics/impact-accuracy${buildQuery({ days })}`, init);
}
