import type { LogValueGroup } from "./analytics";
import { apiFetch, buildQuery } from "./http";

// Types mirror platforms/ingestion-service/src/ingestion/schemas/run.py

/** A run's scope, as the ingestion's `SCOPES` (models/run.py). "impact-subset": only the suggested tests ran
 *  (`run-impact --suggested-only`, or a `--fail-fast` stop). */
export const SCOPES = ["full", "impact-subset"] as const;
export type RunScope = (typeof SCOPES)[number];

/** One stage of a `run-impact` run (spec 2026-10-13 §3.1). */
export interface RunStage {
  name: "suggested" | "rest" | "all";
  duration_s: number;
  tests: number;
  failed: number;
}

export interface RunStages {
  stages: RunStage[];
  /** From the start of stage 1 to the end of the first failing scenario; null without a failure. */
  time_to_first_failure_s: number | null;
  stopped_after_stage: 1 | null;
}

export interface Run {
  id: number;
  project_id: number;
  ci_provider: string;
  ci_run_url: string | null;
  commit_sha: string | null;
  branch: string | null;
  environment: string | null;
  agent_version: string | null;
  commit_author: string | null;
  commit_message: string | null;
  pr_number: number | null;
  base_branch: string | null;
  /** Older servers omit it: a full run. */
  scope?: RunScope;
  /** run-impact's stages; null (or absent) for an ordinary upload. */
  stages?: RunStages | null;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  errored: number;
  change_base_ref: string | null;
  changed_files: number | null;
  additions: number | null;
  deletions: number | null;
  changes_truncated: boolean | null;
  created_at: string;
}

export interface ChangedFile {
  path: string;
  status: string;
  additions: number | null;
  deletions: number | null;
}

export interface RunResult {
  id: number;
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
  status: string;
  duration_ms: number;
  message: string | null;
  details: string | null;
  truncated: boolean;
  redacted: boolean;
  file: string | null;
  owner: string | null;
  /** Failed or errored, and the test is in quarantine: shown, not counted. */
  quarantined?: boolean;
  /** Step screenshots stored for this result (ADR-036); absent from an older server, which reads as 0. */
  screenshot_count?: number;
}

export interface RunComponent {
  name: string;
  sha: string;
}

export interface RunDetail extends Run {
  /** Failing results of quarantined tests. */
  quarantined?: number;
  /** The failing results that count. */
  blocking?: number;
  results: RunResult[];
  changes: ChangedFile[];
  components: RunComponent[];
}

export type RunStatusFilter = "passed" | "failed" | "skipped" | "errored";

/** Server-side filters for the runs list; every field is optional. */
export interface RunFilters {
  branch?: string;
  /** Case-insensitive contains match on the branch (at most 255 characters); ANDed with `branch`. */
  branch_contains?: string;
  status?: "failing" | "passing";
  environment?: string;
  ci_provider?: string;
  commit?: string;
  pr?: number;
  author?: string;
  since?: string; // ISO instant, inclusive
  until?: string; // ISO instant, exclusive
  /** "full" hides runs of only the suggested tests. */
  scope?: RunScope;
  /** Runs with a result holding exactly this log value (spec 2026-10-15 §3.1), under `pattern` when given. */
  value?: string;
  pattern?: string;
}

export function listRuns(
  projectId: number,
  opts: { limit: number; offset: number } & RunFilters,
  init: { signal?: AbortSignal } = {},
): Promise<Run[]> {
  const q = buildQuery({ ...opts });
  return apiFetch(`/api/v1/projects/${projectId}/runs${q}`, init);
}

export interface GroupedTest {
  id: number;
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
  status: string;
  quarantined?: boolean;
}

/** The cause across this run and up to 19 earlier runs of the same branch. */
export interface CauseHistory {
  window: number;
  seen_in: number;
  /** Consecutive runs up to this one with the cause; 1 means it is new. */
  streak: number;
  since_run_id: number;
  since_started_at: string;
}

/** Failed and errored tests that share one cause: the same error once run-specific values are ignored. */
export interface FailureGroup {
  signature: string;
  /** The first message's first line; null when the tests reported no message. */
  headline: string | null;
  count: number;
  failed: number;
  errored: number;
  quarantined?: number;
  /** The first 100; `count` has them all. */
  tests: GroupedTest[];
  history: CauseHistory;
}

/** What the comparison page shows of each run. */
export type RunOverview = Pick<Run, "id" | "started_at" | "branch" | "commit_sha" | "passed" | "failed" | "errored">;

export interface CompareItem {
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
  base_status: string | null;
  head_status: string | null;
  base_duration_ms: number | null;
  head_duration_ms: number | null;
  message: string | null;
}

export interface RunComparison {
  base: Run;
  head: Run;
  counts: Record<"new_failures" | "fixed" | "still_failing" | "slower" | "added" | "removed" | "unchanged", number>;
  new_failures: CompareItem[];
  fixed: CompareItem[];
  still_failing: CompareItem[];
  slower: CompareItem[];
  added: CompareItem[];
  removed: CompareItem[];
}

/** `head` compared with `base`, test by test (each test's last attempt). */
export function compareRuns(headId: number, baseId: number): Promise<RunComparison> {
  return apiFetch(`/api/v1/runs/${headId}/compare/${baseId}`);
}

export function getFailureGroups(
  runId: number,
): Promise<{ total: number; quarantined?: number; blocking?: number; groups: FailureGroup[] }> {
  return apiFetch(`/api/v1/runs/${runId}/failure-groups`);
}

export function getRun(
  runId: number,
  status?: RunStatusFilter,
  extra: { value?: string; pattern?: string } = {},
  init: { signal?: AbortSignal } = {},
): Promise<RunDetail> {
  // With `value`, only the results holding that log value come back; the run's counts are unchanged
  const q = buildQuery({ status, ...extra });
  return apiFetch(`/api/v1/runs/${runId}${q}`, init);
}

/** A run's header and counts, without its results (GET .../runs/{id}/summary). */
export interface RunSummary {
  id: number;
  project_id: number;
  started_at: string;
  finished_at: string;
  branch: string | null;
  commit_sha: string | null;
  environment: string | null;
  status: "passing" | "failing";
  counts: { passed: number; failed: number; errored: number; skipped: number };
  ci_provider: string;
  ci_run_url: string | null;
}

/** 404 for an unknown run or one of another project. */
export function getRunSummary(projectId: number, runId: number, init: { signal?: AbortSignal } = {}): Promise<RunSummary> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/summary`, init);
}

/** A test case that failed at a step, with the text it ran ("When I search Lisb0n"). */
export interface FailedStepTest { test_key: string; name: string; text: string }

/** One step's failures that share an error shape (quoted values, numbers and ids as "…"); `shape` "" means no message. */
export interface FailedStepError { shape: string; example: string | null; cases: number; tests: FailedStepTest[]; more?: number }

export interface FailedStepSince { run_id: number; started_at: string; runs: number; capped: boolean }

/** A step that failed in the run, across its test cases (spec 2026-10-14 §3.3). */
export interface RunFailedStep {
  key: string;
  by: "definition" | "text";
  pattern: string;
  definition?: string;
  cases: number;
  errors: FailedStepError[];
  since: FailedStepSince;
  last_passed?: { run_id: number; started_at: string };
}

export function getRunFailedSteps(
  projectId: number, runId: number, init: { signal?: AbortSignal } = {},
): Promise<{ steps: RunFailedStep[] }> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/failed-steps`, init);
}

/** A result's whole masked log with the values its project's patterns found in it (spec 2026-10-15 §2.1). Read on
 *  demand: the run payload never carries it. */
export interface ResultLog { log: string | null; values: LogValueGroup[] }

export function getResultLog(projectId: number, runId: number, resultId: number): Promise<ResultLog> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/results/${resultId}/log`);
}
