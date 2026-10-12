import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { type CaseAreas, getCaseAreas } from "../../api/cases";
import { ApiError } from "../../api/http";
import { type Report, type ReportRequest, type ReportSectionName, postReport } from "../../api/report";
import { listRepositories } from "../../api/repositories";
import { getRunUrls } from "../../api/runRequests";
import { REPORT_STALE_MS } from "../../lib/reportCache";
import { MAX_REPORT_KEYS, formatArea, resolveScope } from "../../lib/reportScope";
import { ALL_BRANCHES, type ReportFilters, addDays } from "./useReportFilters";

/** Whether the sections can be asked yet: they wait for the default branch, the case-areas join and the Play
 *  URLs they need, and are never sent unfiltered while one of those is missing. */
export type Gate =
  | { state: "wait" }
  | { state: "blocked"; message: string; error?: unknown; retry?: () => void }
  | { state: "ready"; base: Omit<ReportRequest, "sections">; key: readonly unknown[] };

interface Loaded<T> { data?: T; error: unknown; refetch: () => unknown }
export interface GateInput {
  filters: ReportFilters;
  tz: string;
  defaultBranch: string | null;
  caseAreas: Loaded<CaseAreas>;
  runUrls: Loaded<{ urls: string[] }>;
}

export function effectiveBranch(filters: ReportFilters, defaultBranch: string | null): string | null {
  if (filters.branch === ALL_BRANCHES) return null;
  return filters.branch || defaultBranch;
}

/** Play requests are made before their runs start: ask from the previous period's first day, minus one. */
export function runUrlsSince(filters: ReportFilters): string {
  return `${addDays(filters.from, -filters.days - 1)}T00:00:00Z`;
}

export function caseAreasMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409 && error.code === "too_many_cases") {
    return "This project has more cases than the report can join (50,000)";
  }
  return "Cases could not be loaded";
}

export function computeGate({ filters, tz, defaultBranch, caseAreas, runUrls }: GateInput): Gate {
  if (filters.branch === "" && defaultBranch === null) return { state: "wait" };
  let keys: string[] | null = null;
  let version: string | null = null;
  if (filters.area !== null || filters.suite !== null) {
    if (caseAreas.error) {
      return { state: "blocked", message: caseAreasMessage(caseAreas.error), error: caseAreas.error, retry: () => void caseAreas.refetch() };
    }
    if (!caseAreas.data) return { state: "wait" };
    const scope = resolveScope(caseAreas.data, filters.area, filters.suite);
    if (scope.kind === "empty") return { state: "blocked", message: "No automated tests are linked to cases in this area" };
    if (scope.kind === "too_many") {
      return { state: "blocked", message: `This selection has more than ${MAX_REPORT_KEYS.toLocaleString("en")} automated tests. Narrow it with another filter.` };
    }
    if (scope.kind === "keys") keys = scope.keys;
    // Only a key filter depends on case-areas, so only then does its version join the query key
    version = caseAreas.data.generatedAt;
  }
  let urls: string[] | null = null;
  if (filters.origin !== "any") {
    if (runUrls.error) {
      return { state: "blocked", message: "Play requests could not be loaded", error: runUrls.error, retry: () => void runUrls.refetch() };
    }
    if (!runUrls.data) return { state: "wait" };
    urls = runUrls.data.urls;
  }
  const branch = effectiveBranch(filters, defaultBranch);
  return {
    state: "ready",
    base: {
      from: filters.from, to: filters.to, tz, branch, environment: filters.environment || null,
      ci_provider: filters.ci || null, origin: filters.origin, requested_run_urls: urls, test_keys: keys, bucket: "auto",
    },
    // The filters, never the keys: the keys follow from the filters and the case-areas version
    key: [{
      from: filters.from, to: filters.to, tz, branch, environment: filters.environment, ci: filters.ci,
      origin: filters.origin, area: filters.area ? formatArea(filters.area) : null, suite: filters.suite,
    }, version],
  };
}

/** The first repository's default branch, else main (plan Ruling 1); null while loading. */
export function useDefaultBranch(projectId: number): string | null {
  const repos = useQuery({
    queryKey: ["repositories", projectId], queryFn: () => listRepositories(projectId), staleTime: REPORT_STALE_MS, retry: false,
  });
  if (repos.isPending) return null;
  return repos.data?.[0]?.default_branch || "main";
}

/** Test management's case areas for the coverage join (ADR-026). The Report and the Overview's Coverage share it. */
export const caseAreasQuery = (projectId: number) => ({
  queryKey: ["case-areas", projectId] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => getCaseAreas(projectId, { signal }),
  staleTime: REPORT_STALE_MS,
  retry: false,
});

export function useReportRequest(projectId: number, filters: ReportFilters, tz: string, opts: { loadCaseAreas: boolean }) {
  const defaultBranch = useDefaultBranch(projectId);
  const needAreas = opts.loadCaseAreas || filters.area !== null || filters.suite !== null;
  const caseAreas = useQuery({ ...caseAreasQuery(projectId), enabled: needAreas });
  const since = runUrlsSince(filters);
  const runUrls = useQuery({
    queryKey: ["run-urls", projectId, since], queryFn: ({ signal }) => getRunUrls(projectId, since, { signal }),
    enabled: filters.origin !== "any", staleTime: REPORT_STALE_MS, retry: false,
  });
  const { data: areasData, error: areasError, refetch: refetchAreas } = caseAreas;
  const { data: urlsData, error: urlsError, refetch: refetchUrls } = runUrls;
  const gate = useMemo(
    () => computeGate({
      filters, tz, defaultBranch,
      caseAreas: { data: areasData, error: areasError, refetch: refetchAreas },
      runUrls: { data: urlsData, error: urlsError, refetch: refetchUrls },
    }),
    [filters, tz, defaultBranch, areasData, areasError, refetchAreas, urlsData, urlsError, refetchUrls],
  );
  return { gate, caseAreas, runUrls, defaultBranch, effectiveBranch: effectiveBranch(filters, defaultBranch) };
}

/** One request per section, so each loads and fails on its own; a filter change aborts the one in flight. */
export function useReportSection(projectId: number, gate: Gate, section: ReportSectionName) {
  return useQuery<Report>({
    queryKey: ["report", projectId, section, ...(gate.state === "ready" ? gate.key : [])],
    queryFn: ({ signal }) => {
      if (gate.state !== "ready") throw new Error("The report is not ready to be asked");
      return postReport(projectId, { ...gate.base, sections: [section] }, { signal });
    },
    enabled: gate.state === "ready",
    staleTime: REPORT_STALE_MS,
    retry: false,
  });
}
