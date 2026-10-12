import { type Case, searchCases } from "../api/cases";
import { getRunImpact, type ImpactSuggestion, scoreChange, type SuggestedTest } from "../api/impact";
import { listRuns, type Run } from "../api/runs";
import { isRunnable } from "../components/CaseTable";

/** How far back the branch's latest change is looked for (plan Ruling 23). */
export const RECENT_RUNS = 20;
const PAGE = 200; // test-management's search limit
const MAX_PAGES = 5;

export interface LikelyAffected {
  /** The branch's latest run with changed files. */
  run: Run;
  suggestion: ImpactSuggestion;
  /** Runnable (imported, active) cases linked to suggested tests, strongest suggestion first. */
  cases: Case[];
  /** Suggested tests no case links to: not runnable from QEOS. */
  unlinked: SuggestedTest[];
  /** Suggested tests whose only linked cases are manual (or archived): Play rejects those, so not runnable either. */
  manualOnly: SuggestedTest[];
}

/** The branch's latest run counts changed files, but none can be read back (e.g. purged): nothing to score. */
export interface NoReadableChange {
  run: Run;
  suggestion: null;
}

export interface LinkedCases {
  cases: Case[];
  unlinked: SuggestedTest[];
  manualOnly: SuggestedTest[];
}

/** Suggested test keys to cases through `automated_test_key` (plan Ruling 24). Archived cases are left out by the search;
 *  test-management compares keys lowercased. Only runnable cases are returned: Play refuses a whole run that holds a
 *  manual case, so a test linked only to manual cases is reported apart. */
export async function linkCases(projectId: number, tests: SuggestedTest[]): Promise<LinkedCases> {
  if (tests.length === 0) return { cases: [], unlinked: [], manualOnly: [] };
  const keys = tests.map((t) => t.test_key.toLowerCase());
  const cases: Case[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const found = await searchCases(projectId, { labels: [], test_keys: keys, keys_mode: "include", limit: PAGE, offset: page * PAGE });
    cases.push(...found.items);
    if (found.items.length === 0 || cases.length >= found.total) break;
  }
  const rank = new Map(keys.map((key, index) => [key, index]));
  const position = (c: Case) => rank.get(c.automated_test_key?.toLowerCase() ?? "") ?? keys.length;
  cases.sort((a, b) => position(a) - position(b) || a.number - b.number);
  const keyOf = (c: Case) => c.automated_test_key?.toLowerCase();
  const linked = new Set(cases.map(keyOf));
  const runnable = cases.filter(isRunnable);
  const runs = new Set(runnable.map(keyOf));
  const key = (t: SuggestedTest) => t.test_key.toLowerCase();
  return {
    cases: runnable,
    unlinked: tests.filter((t) => !linked.has(key(t))),
    manualOnly: tests.filter((t) => linked.has(key(t)) && !runs.has(key(t))),
  };
}

/** The branch's latest change scored now (spec 2026-10-12 §2.2): the newest of its last 20 runs with changed files gives
 *  the paths, POST /analytics/impact scores them, and the cases' automated_test_key maps the tests. Null when no recent
 *  run of the branch carries change data; `suggestion: null` when that run's changed files cannot be read. */
export async function findLikelyAffected(projectId: number, branch: string): Promise<LikelyAffected | NoReadableChange | null> {
  const runs = await listRuns(projectId, { limit: RECENT_RUNS, offset: 0, branch });
  const run = runs.find((r) => (r.changed_files ?? 0) > 0);
  if (run === undefined) return null;
  const { changed_paths: paths } = await getRunImpact(projectId, run.id);
  if (paths.length === 0) return { run, suggestion: null };
  const suggestion = await scoreChange(projectId, paths, branch);
  return { run, suggestion, ...(await linkCases(projectId, suggestion.tests)) };
}
