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
/** A period for latest-keys: ISO instants, `until` exclusive, on the run's start. */
export interface KeysWindow { since: string; until: string }

/** Keys of the tests whose latest result has `status`; with a window, only the results of runs started in it count,
 *  so "latest" is the latest within it and `any` lists every test that ran in it. */
export function getLatestKeys(
  projectId: number,
  status: "passed" | "failed" | "skipped" | "any",
  window?: KeysWindow,
): Promise<{ keys: string[] }> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/latest-keys${buildQuery({ status, ...window })}`);
}

export type StripStatus = "passed" | "failed" | "rerun" | "skipped";
/** One result in a test's strip: the run it was in and the test's status there. */
/** One pattern's values in a result or a run (log values, ADR-032): patterns in name order, values in log order. */
export interface LogValueGroup { name: string; values: string[] }
/** One result in a test's strip: the run it was in, the test's status there and its log values (absent from an older
 *  server). */
export interface StripEntry {
  run_id: number; started_at: string; branch: string | null; status: StripStatus; values?: LogValueGroup[];
}

/** Each test's own last results (oldest to newest), only runs it was in; keyed by lowercase test key. */
export function getRunStrip(
  projectId: number,
  testKeys: string[],
  limit = 10,
): Promise<{ tests: Record<string, StripEntry[]> }> {
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
  started_at: string; message: string | null;
  /** The id of the result shown, for its log (spec 2026-10-15 §2.1); absent from an older server. */
  result_id?: number;
  /** `key` names the step across the run's test cases (the run page's `#step-<key>`); `definition`/`pattern` from collector 0.8.0. */
  failed_step?: { text: string; line?: number; definition?: string; pattern?: string; key?: string };
  /** Log values of this result, each pattern with its link template (ADR-032); absent from an older server. */
  values?: (LogValueGroup & { link_template: string | null })[];
  /** Steps of this result that have screenshots, with how many each (ADR-036); absent from an older server. */
  /** Traces stored for this result (ADR-037); absent from an older server, which reads as 0. */
  trace_count?: number;
  screenshot_steps?: { step_text: string; step_line: number | null; hook: "before" | "after" | null; count: number }[];
}

/** Each test's latest result on any branch, with the failed step; at most 500 keys per call. With `runId`, each test's
 *  result in that run instead (tests not in it are absent; a run of another project is a 404). */
export function getLatestResults(projectId: number, keys: string[], runId?: number): Promise<{ results: Record<string, LatestResult> }> {
  const body = runId == null ? { keys } : { keys, run_id: runId };
  return apiFetch(`/api/v1/projects/${projectId}/analytics/latest-results`, { method: "POST", body: JSON.stringify(body) });
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
