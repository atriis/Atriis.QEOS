import { listRuns, type RunFilters } from "../api/runs";
import { LIVE_REFRESH_MS } from "./live";

/** The Runs view's page size. */
export const RUNS_PAGE_SIZE = 50;

/** The Runs view's first page for these filters, under its own key and polled as it is (ADR-021). Undefined filter
 *  fields drop out of the key, so `{ branch: "main" }` is the view's key with only Branch applied. */
export const runsFirstPageQuery = (projectId: number, filters: RunFilters) => ({
  queryKey: ["runs", projectId, filters, 0] as const,
  queryFn: () => listRuns(projectId, { limit: RUNS_PAGE_SIZE, offset: 0, ...filters }),
  refetchInterval: LIVE_REFRESH_MS,
});

/** What a new latest run makes stale among the Runs view's pages: `{}` partially matches every filters object, so this
 *  prefix covers each page whatever its filters, and not the latest-run query (`["runs", id, "latest"]`), which is the
 *  one that noticed the new run. */
export const runsPagesStaleKey = (projectId: number) => ["runs", projectId, {}] as const;
