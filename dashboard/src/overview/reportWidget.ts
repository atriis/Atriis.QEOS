import type { ReportSectionName } from "../api/report";
import { ALL_BRANCHES, type ReportFilters, addDays, todayIn } from "../pages/report/useReportFilters";
import { computeGate, useReportSection } from "../pages/report/useReportRequest";
import { viewLink } from "./links";

// A widget filters by period and branch only, so the Report's case-areas and Play-URL inputs are never needed
const NOT_NEEDED = { data: undefined, error: null, refetch: () => undefined };

const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** The Report's filters for a widget: the last `period` days up to today, on one branch or (none set) every branch. */
export function reportFilters(period: number, branch: string | undefined, today: string): ReportFilters {
  return {
    preset: null, from: addDays(today, -(period - 1)), to: today, days: period,
    branch: branch ?? ALL_BRANCHES, environment: "", ci: "", origin: "any", area: null, suite: null,
  };
}

/** One Report section for a widget (spec §4): `sections: [section]` under the Report's own query key, so the Report page
 *  with the same period and branch reuses the answer, and so do two widgets that ask the same. Not polled; a new latest
 *  run makes it stale (the widget's `staleKeys`). */
export function useWidgetReport(projectId: number, section: ReportSectionName, period: number, branch: string | undefined) {
  const tz = browserZone();
  const gate = computeGate({
    filters: reportFilters(period, branch, todayIn(tz)), tz, defaultBranch: null, caseAreas: NOT_NEEDED, runUrls: NOT_NEEDED,
  });
  return useReportSection(projectId, gate, section);
}

/** The Report with the same period and branch, at the widget's section (plan Ruling 16): its 7- and 30-day presets by
 *  name, 14 days as a from-to range; no branch set sends `branch=*`, since the Report reads no branch as the default one. */
export function reportLink(projectId: number, period: number, branch: string | undefined, anchor: string): string {
  let range: Record<string, string>;
  if (period === 7 || period === 30) {
    range = { period: String(period) };
  } else {
    const today = todayIn(browserZone());
    range = { from: addDays(today, -(period - 1)), to: today };
  }
  return `${viewLink(`/projects/${projectId}/report`, range, branch, { everyBranch: ALL_BRANCHES })}#${anchor}`;
}

/** What a new latest run makes stale for a widget asking one Report section: that section's queries. */
export const reportStaleKeys = (section: ReportSectionName) => (projectId: number) => [["report", projectId, section]];
