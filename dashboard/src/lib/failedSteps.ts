import { useQueries } from "@tanstack/react-query";
import type { LatestResult } from "../api/analytics";
import { searchCases } from "../api/cases";
import { type FailedStepSince, type RunFailedStep, getRunFailedSteps } from "../api/runs";
import { plural } from "./words";

export const TEXT_GROUPED_NOTE = "Grouped by step text: update the collector to 0.8.0 to group parameter variations.";
const STALE_MS = 60_000;
const CAP_RUNS = 50;
const SEARCH_PAGE = 200; // test-management's search limit
const SEARCH_PAGES = 5;
const day = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/** One run's failed steps, under one key for the run page and every tooltip of that run. */
export const failedStepsQuery = (projectId: number, runId: number) => ({
  queryKey: ["failed-steps", projectId, runId] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => getRunFailedSteps(projectId, runId, { signal }),
  staleTime: STALE_MS,
});

export const stepAnchor = (key: string) => `step-${key}`;
export const stepHref = (projectId: number, runId: number, key: string) => `/projects/${projectId}/runs/${runId}#${stepAnchor(key)}`;

/** A capped streak by what capped it: 50 runs, else the 90-day window (plan ruling R5). */
const cappedText = (since: FailedStepSince) =>
  since.runs >= CAP_RUNS ? `failing for more than ${CAP_RUNS} runs` : "failing for more than 90 days";

/** The run page's line: "failing since run #430, 14 Oct (5 runs) · last passed in run #429". */
export function sinceText(step: RunFailedStep): string {
  const { since, last_passed } = step;
  const base = since.capped ? cappedText(since)
    : since.runs === 1 ? "new in this run"
    : `failing since run #${since.run_id}, ${day.format(new Date(since.started_at))} (${plural(since.runs, "run", "runs")})`;
  return last_passed ? `${base} · last passed in run #${last_passed.run_id}` : base;
}

/** The tooltip's line: "Also failed in 11 other test cases in this run · failing since run #430". */
export function spreadText(step: RunFailedStep): string {
  const others = step.cases - 1;
  const wide = others > 0 ? `Also failed in ${plural(others, "other test case", "other test cases")} in this run` : "Only this test case";
  const since = step.since.capped ? cappedText(step.since) : step.since.runs === 1 ? "new in this run" : `failing since run #${step.since.run_id}`;
  return `${wide} · ${since}`;
}

/** Test keys (lowercased) to the case each is linked to, the lowest number when several are; archived cases are left
 *  out by the search, so their tests link to their history (plan ruling R9). */
export async function casesByTestKey(projectId: number, keys: string[]): Promise<Map<string, number>> {
  const found = new Map<string, number>();
  for (let page = 0; page < SEARCH_PAGES; page++) {
    const res = await searchCases(projectId, { labels: [], test_keys: keys, keys_mode: "include", limit: SEARCH_PAGE, offset: page * SEARCH_PAGE });
    for (const c of res.items) {
      const key = c.automated_test_key?.toLowerCase();
      const known = key != null ? found.get(key) : undefined;
      if (key != null && (known == null || c.number < known)) found.set(key, c.number);
    }
    if (res.items.length === 0 || (page + 1) * SEARCH_PAGE >= res.total) break;
  }
  return found;
}

/** The tooltip's spread line and the link to the step's row on the run page. */
export interface StepSpread { text: string; href: string }

/** For a page's failed-step tooltips: one failed-steps request per run among `results` (shared by every card and
 *  with the run page), then each result's line, once its run has answered (plan ruling R8). */
export function useStepSpread(projectId: number, results: (LatestResult | null | undefined)[]) {
  const runIds = [...new Set(results.flatMap((r) => (r?.failed_step?.key ? [r.run_id] : [])))].sort((a, b) => a - b);
  const answers = useQueries({ queries: runIds.map((runId) => failedStepsQuery(projectId, runId)) });
  return (result: LatestResult | null | undefined): StepSpread | undefined => {
    const key = result?.failed_step?.key;
    if (!result || !key) return undefined;
    const step = answers[runIds.indexOf(result.run_id)]?.data?.steps.find((s) => s.key === key);
    return step ? { text: spreadText(step), href: stepHref(projectId, result.run_id, key) } : undefined;
  };
}
