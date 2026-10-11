import { getFlaky, getTrends } from "../api/analytics";

/** The Flaky view's default thresholds: the Overview card and the Cases tile count the same tests it lists. */
export const FLAKY_DEFAULTS = { windowDays: 14, minRuns: 5, minFlipRate: 0.3 } as const;

/** Project health figures are re-asked at most once a minute (a new upload invalidates them on Overview). */
const HEALTH_STALE_MS = 60_000;

/** The flaky tests at the default thresholds, quarantined ones included (`muted`), so a reader can count both.
 *  Overview and the Cases tile share it. */
export const flakyHealthQuery = (projectId: number) => ({
  queryKey: ["flaky", projectId, "health"] as const,
  queryFn: () => getFlaky(projectId, { ...FLAKY_DEFAULTS, includeMuted: true }),
  staleTime: HEALTH_STALE_MS,
});

/** The Flaky view's own query at its default thresholds for another window, quarantined tests left out (its "Show
 *  quarantined" off): the Overview's Flaky tests widget set to 7 or 30 days shares the view's answer. */
export const flakyWindowQuery = (projectId: number, windowDays: number) => ({
  queryKey: ["flaky", projectId, windowDays, FLAKY_DEFAULTS.minRuns, FLAKY_DEFAULTS.minFlipRate, "", false] as const,
  queryFn: () => getFlaky(projectId, { windowDays, minRuns: FLAKY_DEFAULTS.minRuns, minFlipRate: FLAKY_DEFAULTS.minFlipRate }),
  staleTime: HEALTH_STALE_MS,
});

/** This week's and last week's pass rate (two weekly buckets). Overview and the Cases tile share it; a branch (the
 *  Overview widget's setting) joins the key only when one is chosen, and no branch means every branch. */
export const passRateWeeksQuery = (projectId: number, tz: string, branch?: string) => ({
  queryKey: (branch
    ? ["trends", projectId, "overview-weeks", tz, branch]
    : ["trends", projectId, "overview-weeks", tz]) as readonly unknown[],
  queryFn: () => getTrends(projectId, { days: 14, tz, bucket: "week", branch }),
  staleTime: HEALTH_STALE_MS,
});
