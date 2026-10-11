import { getFailureGroups, listRuns, type Run } from "../api/runs";
import { LIVE_REFRESH_MS } from "../lib/live";

/** The project's newest run, polled every 30 s while the tab is visible (ADR-021). The page, Latest run and Failing in
 *  latest run share this one query. */
export const latestRunQuery = (projectId: number) => ({
  queryKey: ["runs", projectId, "latest"] as const,
  queryFn: () => listRuns(projectId, { limit: 1, offset: 0 }),
  refetchInterval: LIVE_REFRESH_MS,
});

/** The latest run's failures grouped by cause; asked only when something failed. */
export const failureGroupsQuery = (run: Run | undefined) => ({
  queryKey: ["failure-groups", run?.id] as const,
  queryFn: () => getFailureGroups(run!.id),
  enabled: run !== undefined && run.failed + run.errored > 0,
});

/** What a new latest run makes stale (plan Ruling 27): figures that are not polled refetch once, not on every tick. */
export const newRunStaleKeys = (projectId: number): (readonly unknown[])[] => [
  ["trends", projectId], ["flaky", projectId], ["report", projectId], ["branches", projectId], ["latest-keys", projectId],
];
