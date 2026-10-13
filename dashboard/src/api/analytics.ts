import { apiFetch, buildQuery } from "./http";

// Types mirror platforms/ingestion-service/src/ingestion/schemas/analytics.py (the run-strip types below are hand-written; see the run-strip route).

export interface TrendDay {
  date: string;
  runs: number;
  total: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  pass_rate: number | null;
  avg_run_duration_ms: number | null;
  max_run_duration_ms: number | null;
}

export type TrendBucket = "day" | "week" | "month";

export interface Trends {
  tz: string;
  bucket: TrendBucket;
  days: TrendDay[];
}

export interface StatsRow {
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
  runs: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  pass_rate: number | null;
  avg_duration_ms: number | null;
  last_status: string;
  last_seen: string;
}

export interface Execution {
  run_id: number;
  started_at: string;
  branch: string | null;
  commit_sha: string | null;
  environment: string | null;
  status: string;
  duration_ms: number;
  message: string | null;
}

export interface History {
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
  summary: {
    runs: number;
    passed: number;
    failed: number;
    errored: number;
    skipped: number;
    pass_rate: number | null;
    avg_duration_ms: number | null;
  };
  executions: Execution[];
}

export interface CommitRef {
  commit_sha: string;
  environment: string | null;
}

export interface FlakyRow {
  test_key: string;
  muted?: boolean;
  suite: string;
  class_name: string;
  name: string;
  reason: "same_commit" | "flips";
  commits: CommitRef[];
  flips: number | null;
  flip_rate: number | null;
  runs: number;
  last_status: string;
  last_seen: string;
}

export function getTrends(
  projectId: number,
  opts: { days: number; tz: string; bucket?: TrendBucket; branch?: string; environment?: string },
): Promise<Trends> {
  const q = buildQuery({
    days: opts.days, tz: opts.tz,
    bucket: opts.bucket && opts.bucket !== "day" ? opts.bucket : undefined,
    branch: opts.branch, environment: opts.environment,
  });
  return apiFetch(`/api/v1/projects/${projectId}/analytics/trends${q}`);
}

/** Test keys whose most recent result has the status ("any": at least one result). */
export function getLatestKeys(
  projectId: number,
  status: "passed" | "failed" | "skipped" | "any",
): Promise<{ keys: string[] }> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/latest-keys${buildQuery({ status })}`);
}

export type StripStatus = "passed" | "failed" | "rerun" | "skipped" | null;
export interface StripRun { id: number; started_at: string; branch: string | null }

/** Each test's status in the project's last runs (oldest to newest); statuses are keyed by lowercase test key. */
export function getRunStrip(
  projectId: number,
  testKeys: string[],
  limit = 10,
): Promise<{ runs: StripRun[]; statuses: Record<string, StripStatus[]> }> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/run-strip`, {
    method: "POST",
    body: JSON.stringify({ test_keys: testKeys, limit }),
  });
}

export interface DurationEstimate {
  /** Null when no test has history. */
  estimate_ms: number | null;
  upper_ms: number | null;
  tests_with_history: number;
  tests_without_history: number;
  /** Tests whose durations came from the requested environment only. */
  environment_used: number;
  model: { overhead_ms: number; factor: number; runs: number; fitted: boolean };
}

/** How long a Play of these tests should take (1–200 keys), from the project's last 30 days. */
export function getDurationEstimate(projectId: number, testKeys: string[], environment?: string): Promise<DurationEstimate> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/duration-estimate`, {
    method: "POST",
    body: JSON.stringify(environment ? { test_keys: testKeys, environment } : { test_keys: testKeys }),
  });
}

export function getTests(
  projectId: number,
  opts: { days: number; sort: "failures" | "duration" | "name"; search?: string; limit: number; offset: number },
  init: { signal?: AbortSignal } = {},
): Promise<StatsRow[]> {
  const q = buildQuery({ days: opts.days, sort: opts.sort, search: opts.search, limit: opts.limit, offset: opts.offset });
  return apiFetch(`/api/v1/projects/${projectId}/analytics/tests${q}`, init);
}

export function getHistory(
  projectId: number,
  testKey: string,
  opts: { days: number; branch?: string; limit: number },
): Promise<History> {
  const q = buildQuery({ days: opts.days, branch: opts.branch, limit: opts.limit });
  return apiFetch(`/api/v1/projects/${projectId}/analytics/tests/${encodeURIComponent(testKey)}/history${q}`);
}

export function muteFlaky(projectId: number, testKey: string): Promise<void> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/flaky/mute`, {
    method: "PUT",
    body: JSON.stringify({ test_key: testKey }),
  });
}

export function unmuteFlaky(projectId: number, testKey: string): Promise<void> {
  return apiFetch(
    `/api/v1/projects/${projectId}/analytics/flaky/mute/${encodeURIComponent(testKey)}`,
    { method: "DELETE" },
  );
}

export interface BranchStats {
  branch: string | null;
  runs: number;
  total: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  pass_rate: number | null;
  last_seen: string;
}

export function getBranches(
  projectId: number,
  opts: { days: number; limit?: number },
): Promise<BranchStats[]> {
  const q = buildQuery({ days: opts.days, limit: opts.limit });
  return apiFetch(`/api/v1/projects/${projectId}/analytics/branches${q}`);
}

export function getFlaky(
  projectId: number,
  opts: { windowDays: number; minRuns: number; minFlipRate: number; branch?: string; includeMuted?: boolean },
  init: { signal?: AbortSignal } = {},
): Promise<FlakyRow[]> {
  const q = buildQuery({
    window_days: opts.windowDays,
    min_runs: opts.minRuns,
    min_flip_rate: opts.minFlipRate,
    branch: opts.branch,
    include_muted: opts.includeMuted ? "true" : undefined,
  });
  return apiFetch(`/api/v1/projects/${projectId}/analytics/flaky${q}`, { signal: init.signal });
}

export interface LatestResult {
  status: string; run_id: number; branch: string | null; environment: string | null;
  started_at: string; message: string | null; failed_step?: { text: string; line?: number };
}

/** Each test's latest result on any branch, with the failed step; at most 500 keys per call. */
export function getLatestResults(projectId: number, keys: string[]): Promise<{ results: Record<string, LatestResult> }> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/latest-results`, { method: "POST", body: JSON.stringify({ keys }) });
}

const COUNT = new Intl.NumberFormat();

/** A count in the reader's locale ("2,124"): the Report and the Overview widgets print counts the same way. */
export function formatCount(n: number): string {
  return COUNT.format(n);
}

export function formatPassRate(rate: number | null): string {
  if (rate === null) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms} ms`;
  // Round first, then split: 59.95 s rounds to 60.0 s, which reads "1m 00s"; 119.5 s to 120 s, "2m 00s"
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1)} s`;
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
}
