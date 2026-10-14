import { type Case, type CaseQuery, type CaseStatus, type Priority, type FeatureGroup, getFeatureDetail, listCases } from "../api/cases";
import type { StripEntry, StripStatus } from "../api/analytics";
import type { CaseRowData } from "../components/CaseTable";

/** A page of the Feature view. */
export const FEATURES_PAGE = 50;
/** The most cases one feature row shows when expanded, and the most a fallback grouping reads. */
export const GROUP_CASES_MAX = 200;

const PRIORITY_ORDER: Priority[] = ["low", "medium", "high", "critical"];
/** The order a feature row lists its statuses in. */
export const STATUS_ORDER: CaseStatus[] = ["ready", "draft", "archived"];

/** A feature file's name for display: its file name without a trailing ".feature" (any case). */
export const fileLabel = (path: string) => path.slice(path.lastIndexOf("/") + 1).replace(/\.feature$/i, "");

/** Worst first: what a feature's run shows when its scenarios disagree. */
const WORST: StripStatus[] = ["failed", "rerun", "passed", "skipped"];

/** A feature's strip from its scenarios' strips: the newest `limit` runs any scenario was in, oldest to newest, each
 *  with the worst status present (failed > rerun > passed > skipped). Exact when every strip holds that test's last
 *  `limit` results: a run among the newest `limit` with any scenario is among each of its scenarios' newest `limit`. */
export function mergeStrips(perTest: StripEntry[][], limit = 10): StripEntry[] {
  const byRun = new Map<number, StripEntry>();
  for (const entry of perTest.flat()) {
    const seen = byRun.get(entry.run_id);
    if (!seen || WORST.indexOf(entry.status) < WORST.indexOf(seen.status)) byRun.set(entry.run_id, entry);
  }
  const runs = [...byRun.values()].sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.run_id - b.run_id);
  return runs.slice(-limit);
}

/** A feature group, with its cases when the page grouped them itself (filters the feature list cannot apply). */
export interface FeatureRow extends FeatureGroup {
  cases?: CaseRowData[];
}

export const featureDetailQuery = (projectId: number, path: string) => ({
  queryKey: ["feature", projectId, path] as const,
  queryFn: () => getFeatureDetail(projectId, path),
});

/** The folder of a repo-relative path, "" at the root (as the server reports it). */
export const folderOf = (path: string | null) => (path == null ? null : path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

/** The scenarios a feature row expands to, in file order. A file's come from its detail, kept to the row's
 *  filtered case numbers; the manual group's from /cases with the same filters (manual cases have no file). */
export const groupCasesQuery = (projectId: number, row: FeatureRow, filters: Omit<CaseQuery, "limit" | "offset">) => ({
  queryKey: ["feature-cases", projectId, row.path, row.feature_name, row.case_numbers, filters] as const,
  queryFn: async (): Promise<CaseRowData[]> => {
    if (row.cases) return row.cases;
    const wanted = new Set(row.case_numbers);
    if (row.path != null) {
      const detail = await getFeatureDetail(projectId, row.path);
      return detail.cases.filter((c) => wanted.has(c.number)).map((c) => ({ ...c, source_path: detail.path }));
    }
    const page = await listCases(projectId, { ...filters, origin: "manual", limit: GROUP_CASES_MAX, offset: 0 });
    return page.items.filter((c) => c.source_path == null);
  },
  staleTime: 30_000,
});

/** Groups cases the way GET /features does: by (feature name, path), ordered by folder then name, manual last. */
export function groupByFeature(cases: Case[]): FeatureRow[] {
  const groups = new Map<string, FeatureRow>();
  for (const c of cases) {
    const id = c.source_path == null ? "manual" : JSON.stringify([c.feature_name, c.source_path]);
    let g = groups.get(id);
    if (!g) {
      g = { feature_name: c.source_path == null ? null : c.feature_name, path: c.source_path, folder: folderOf(c.source_path),
        case_count: 0, case_numbers: [], test_keys: [], has_source: false, linked_count: 0, top_priority: null,
        status_counts: { draft: 0, ready: 0, archived: 0 }, cases: [] };
      groups.set(id, g);
    }
    g.case_count += 1;
    g.case_numbers.push(c.number);
    if (c.automated_test_key) {
      g.linked_count = (g.linked_count ?? 0) + 1;
      if (!g.test_keys!.includes(c.automated_test_key)) g.test_keys!.push(c.automated_test_key);
    }
    if (g.top_priority == null || PRIORITY_ORDER.indexOf(c.priority) > PRIORITY_ORDER.indexOf(g.top_priority)) g.top_priority = c.priority;
    g.status_counts![c.status] = (g.status_counts![c.status] ?? 0) + 1;
    g.cases!.push(c);
  }
  for (const g of groups.values()) g.test_keys!.sort().splice(GROUP_CASES_MAX);
  const key = (g: FeatureRow) => [g.path == null ? 1 : 0, g.folder ?? "", (g.feature_name ?? "").toLowerCase(), g.path ?? ""] as const;
  return [...groups.values()].sort((a, b) => {
    const [ka, kb] = [key(a), key(b)];
    for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
    return 0;
  });
}
