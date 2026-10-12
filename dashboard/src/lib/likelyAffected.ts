import { type Case, searchCases } from "../api/cases";
import { getRunImpact, type ImpactSuggestion, scoreChange, type SuggestedTest } from "../api/impact";
import { listRuns, type Run } from "../api/runs";

/** How far back the branch's latest change is looked for (plan Ruling 23). */
export const RECENT_RUNS = 20;
const PAGE = 200; // test-management's search limit
const MAX_PAGES = 5;

export interface LikelyAffected {
  /** The branch's latest run with changed files. */
  run: Run;
  suggestion: ImpactSuggestion;
  /** Cases linked to suggested tests, strongest suggestion first. */
  cases: Case[];
  /** Suggested tests no case links to: not runnable from QEOS. */
  unlinked: SuggestedTest[];
}

/** Suggested test keys to cases through `automated_test_key` (plan Ruling 24). Archived cases are left out by the search;
 *  test-management compares keys lowercased. */
export async function linkCases(projectId: number, tests: SuggestedTest[]): Promise<{ cases: Case[]; unlinked: SuggestedTest[] }> {
  if (tests.length === 0) return { cases: [], unlinked: [] };
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
  const linked = new Set(cases.map((c) => c.automated_test_key?.toLowerCase()));
  return { cases, unlinked: tests.filter((t) => !linked.has(t.test_key.toLowerCase())) };
}

/** The branch's latest change scored now (spec 2026-10-12 §2.2): the newest of its last 20 runs with changed files gives
 *  the paths, POST /analytics/impact scores them, and the cases' automated_test_key maps the tests. Null when no recent
 *  run of the branch carries change data. */
export async function findLikelyAffected(projectId: number, branch: string): Promise<LikelyAffected | null> {
  const runs = await listRuns(projectId, { limit: RECENT_RUNS, offset: 0, branch });
  const run = runs.find((r) => (r.changed_files ?? 0) > 0);
  if (run === undefined) return null;
  const { changed_paths: paths } = await getRunImpact(projectId, run.id);
  if (paths.length === 0) return null;
  const suggestion = await scoreChange(projectId, paths, branch);
  return { run, suggestion, ...(await linkCases(projectId, suggestion.tests)) };
}
