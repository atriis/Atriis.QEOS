import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { getTests } from "../api/analytics";
import { listCases, listSuites } from "../api/cases";
import { meQuery } from "../api/auth";
import { ApiError } from "../api/http";
import { listMyOrganizations, listProjects } from "../api/orgs";
import { getRunSummary, listRuns } from "../api/runs";
import { PROJECT_VIEWS } from "../lib/projectViews";
import { readRecent, type RecentItem } from "../lib/recentItems";

export type PaletteItem = RecentItem;

export interface PaletteGroup {
  key: string;
  label: string;
  items: PaletteItem[];
  /** One line in place of the items when the source failed. */
  error?: string;
}

/** Remote sources start from this many characters, ask for this many rows, and wait this long after typing. */
export const MIN_REMOTE = 2;
export const SOURCE_LIMIT = 5;
export const DEBOUNCE_MS = 200;
/** The Test results view's default window, so the palette finds what that list shows. */
const TEST_DAYS = 30;
const RUN_NUMBER = /^#?(\d+)$/;

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

const contains = (text: string, q: string) => text.toLowerCase().includes(q.toLowerCase());

/** The palette's results for `query`, grouped by source. Pages and projects are matched here; cases, tests and runs
 *  are asked of their services in parallel (debounced; a superseded request is aborted through its signal).
 *  Outside a project only pages and projects are offered. */
export function usePaletteGroups(
  query: string,
  projectId: number | null,
): { groups: PaletteGroup[]; pending: boolean; userId: number | undefined } {
  const q = query.trim();
  const debounced = useDebounced(q, DEBOUNCE_MS);
  const remote = projectId !== null && debounced.length >= MIN_REMOTE;
  const runNumber = RUN_NUMBER.exec(debounced)?.[1];

  const orgs = useQuery({ queryKey: ["orgs"], queryFn: listMyOrganizations });
  // The user menu's query: recent items are kept per user
  const userId = useQuery(meQuery).data?.id;
  const projectLists = useQueries({
    queries: (orgs.data ?? []).map((org) => ({ queryKey: ["projects", org.id], queryFn: () => listProjects(org.id) })),
  });

  const opts = { retry: false, staleTime: 30_000 } as const;
  const cases = useQuery({
    queryKey: ["palette", "cases", projectId, debounced],
    queryFn: ({ signal }) => listCases(projectId!, { search: debounced, limit: SOURCE_LIMIT, offset: 0 }, { signal }),
    enabled: remote,
    ...opts,
  });
  const tests = useQuery({
    queryKey: ["palette", "tests", projectId, debounced],
    queryFn: ({ signal }) =>
      getTests(projectId!, { days: TEST_DAYS, sort: "name", search: debounced, limit: SOURCE_LIMIT, offset: 0 }, { signal }),
    enabled: remote,
    ...opts,
  });
  const suites = useQuery({
    queryKey: ["palette", "suites", projectId, debounced],
    queryFn: ({ signal }) => listSuites(projectId!, { search: debounced }, { signal }),
    enabled: remote,
    ...opts,
  });
  const runs = useQuery({
    queryKey: ["palette", "runs", projectId, debounced],
    queryFn: async ({ signal }) => {
      if (runNumber === undefined) return listRuns(projectId!, { branch_contains: debounced, limit: SOURCE_LIMIT, offset: 0 }, { signal });
      try {
        return [await getRunSummary(projectId!, Number(runNumber), { signal })];
      } catch (e) {
        // Not there, or not the reader's to see: either way there is no run to offer
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return [];
        throw e;
      }
    },
    enabled: remote,
    ...opts,
  });

  const recent = useMemo(() => (q === "" ? readRecent(userId) : []), [q, userId]);

  const groups = useMemo(() => {
    const out: PaletteGroup[] = [];
    const recentHere = recent.filter((r) => r.projectId === null || r.projectId === projectId);
    if (recentHere.length > 0) out.push({ key: "recent", label: "Recent", items: recentHere });

    const pages: PaletteItem[] = [
      ...(projectId !== null
        ? PROJECT_VIEWS.map((v) => ({
          id: `page:${projectId}:${v.to}`, kind: "page" as const, label: v.label,
          href: `/projects/${projectId}/${v.to}`, projectId,
        }))
        : []),
      { id: "page:projects", kind: "page", label: "All projects", href: "/", projectId: null },
      ...(orgs.data ?? []).map((o) => ({
        id: `page:org:${o.id}`, kind: "page" as const, label: `${o.name} organization`, href: `/organizations/${o.id}`, projectId: null,
      })),
      { id: "page:security", kind: "page", label: "Security", href: "/account/security", projectId: null },
    ];
    const pageMatches = q === "" ? pages : pages.filter((p) => contains(p.label, q));
    if (pageMatches.length > 0) out.push({ key: "pages", label: "Pages", items: pageMatches });

    if (remote) {
      const source = (key: string, label: string, noun: string, result: { data?: PaletteItem[]; error: unknown }) => {
        const group = result.error != null
          ? { key, label, items: [], error: `Couldn't search ${noun} right now` }
          : result.data && result.data.length > 0 ? { key, label, items: result.data } : null;
        if (!group) return;
        // "#433" asks for a run: its answer leads
        if (key === "runs" && runNumber !== undefined) out.unshift(group);
        else out.push(group);
      };
      source("cases", "Test cases", "test cases", {
        error: cases.error,
        data: cases.data?.items.map((c) => ({
          id: `case:${projectId}:${c.number}`, kind: "case" as const, label: c.title, detail: c.key,
          href: `/projects/${projectId}/cases/${c.number}`, projectId,
        })),
      });
      source("tests", "Test results", "tests", {
        error: tests.error,
        data: tests.data?.map((t) => ({
          id: `test:${projectId}:${t.test_key}`, kind: "test" as const, label: t.name, detail: [t.suite, t.class_name].filter(Boolean).join(" · "),
          href: `/projects/${projectId}/tests/${encodeURIComponent(t.test_key)}`, projectId,
        })),
      });
      source("suites", "Suites", "suites", {
        error: suites.error,
        data: suites.data?.slice(0, SOURCE_LIMIT).map((s) => ({
          id: `suite:${projectId}:${s.id}`, kind: "suite" as const, label: s.name,
          detail: `${s.case_count} ${s.case_count === 1 ? "case" : "cases"}`,
          href: `/projects/${projectId}/suites/${s.id}`, projectId,
        })),
      });
      source("runs", "Runs", "runs", {
        error: runs.error,
        data: runs.data?.map((r) => {
          const { id, branch } = r;
          const broken = "counts" in r ? r.counts.failed + r.counts.errored : r.failed + r.errored;
          return {
            id: `run:${r.project_id}:${id}`, kind: "run" as const, label: `Run #${id}`,
            detail: [branch, broken > 0 ? `${broken} failed` : "passed"].filter(Boolean).join(" · "),
            href: `/projects/${r.project_id}/runs/${id}`, projectId: r.project_id,
          };
        }),
      });
    }

    if (q !== "") {
      const projects = (orgs.data ?? []).flatMap((o, i) =>
        (projectLists[i]?.data ?? []).filter((p) => contains(p.name, q)).map((p) => ({
          id: `project:${p.id}`, kind: "project" as const, label: p.name, detail: o.name, href: `/projects/${p.id}/overview`, projectId: null,
        })));
      if (projects.length > 0) out.push({ key: "projects", label: "Projects", items: projects });
    }
    return out;
  }, [recent, projectId, q, orgs.data, projectLists, remote, runNumber, cases.data, cases.error, tests.data, tests.error, suites.data, suites.error, runs.data, runs.error]);

  // Typed but not yet asked (the debounce) counts as pending, so "no matches" never flashes before the answer
  const waiting = projectId !== null && q.length >= MIN_REMOTE && debounced !== q;
  const pending = waiting || (remote && (cases.isPending || tests.isPending || suites.isPending || runs.isPending));
  return { groups, pending, userId };
}
