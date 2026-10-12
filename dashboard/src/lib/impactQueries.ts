import type { QueryKey } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { formatCount } from "../api/analytics";
import { type AccuracyDays, getImpactAccuracy, getRunImpact } from "../api/impact";
import { REPORT_STALE_MS } from "../pages/report/useReportRequest";

export const ACCURACY_DAYS: readonly AccuracyDays[] = [7, 14, 30];

/** A run's stored suggestion and its outcome (spec 2026-10-12 §2.1). */
export const runImpactQuery = (projectId: number, runId: number) => ({
  queryKey: ["run-impact", projectId, runId] as const,
  queryFn: () => getRunImpact(projectId, runId),
});

/** The accuracy figure under the Report's key (plan Ruling 20): the Report's Refresh and a new latest run refresh it.
 *  The Report's Test impact section and the Overview's Impact accuracy widget share it (spec §4). */
export const impactAccuracyQuery = (projectId: number, days: AccuracyDays) => ({
  queryKey: ["report", projectId, "impact-accuracy", days] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => getImpactAccuracy(projectId, days, { signal }),
  staleTime: REPORT_STALE_MS,
  retry: false,
});

export function useImpactAccuracy(projectId: number, days: AccuracyDays) {
  return useQuery(impactAccuracyQuery(projectId, days));
}

/** What a new latest run makes stale for the accuracy figure (the widget's `staleKeys`). */
export const impactAccuracyStaleKeys = (projectId: number): QueryKey[] => [["report", projectId, "impact-accuracy"]];

/** The Report's period when it is the last 7, 14 or 30 days up to today, else 30 days (plan Ruling 21). */
export function accuracyDays(days: number, to: string, today: string): AccuracyDays {
  return to === today && (ACCURACY_DAYS as readonly number[]).includes(days) ? (days as AccuracyDays) : 30;
}

/** "9 of 12 new failures". */
export function caughtText(caught: number, missed: number): string {
  const total = caught + missed;
  return `${formatCount(caught)} of ${formatCount(total)} new ${total === 1 ? "failure" : "failures"}`;
}

/** A base rate as the evidence line says it: "normally 3%", "normally under 1%"; null when the API has none
 *  (the test never newly failed otherwise), so the line leaves that part out. */
export function normally(rate: number | null): string | null {
  if (rate === null) return null;
  const percent = Math.round(rate * 100);
  return rate > 0 && percent === 0 ? "normally under 1%" : `normally ${percent}%`;
}
