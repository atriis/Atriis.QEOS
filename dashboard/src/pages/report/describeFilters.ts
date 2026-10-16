import type { AppliedFilter } from "../../components/FilterChips";
import type { CaseAreas } from "../../api/cases";
import { CI_LABELS } from "../../lib/ciProviders";
import { AREA_NAMES } from "../../lib/reportScope";
import { ALL_BRANCHES, type ReportFilters } from "./useReportFilters";

export const LINKED_ONLY = "Only automated tests linked to a case are counted";

/** Every filter in force, as people name it: the chips, the subtitle and the print header all read this. */
export function describeFilters(f: ReportFilters, defaultBranch: string | null, areas?: CaseAreas): AppliedFilter[] {
  const out: AppliedFilter[] = [];
  if (f.branch === ALL_BRANCHES) out.push({ key: "branch", name: "Branch", value: "all branches" });
  else if (f.branch) out.push({ key: "branch", name: "Branch", value: f.branch });
  else if (defaultBranch) out.push({ key: "branch", name: "Branch", value: `${defaultBranch} (default)` });
  if (f.environment) out.push({ key: "env", name: "Environment", value: f.environment });
  if (f.ci) out.push({ key: "ci", name: "CI", value: CI_LABELS[f.ci] ?? f.ci });
  if (f.origin !== "any") out.push({ key: "origin", name: "Origin", value: f.origin === "ci" ? "CI" : "Requested from QEOS" });
  if (f.area) out.push({ key: "area", name: AREA_NAMES[f.area.kind], value: f.area.value, title: LINKED_ONLY });
  if (f.suite !== null) {
    const name = areas?.suites.find((s) => s.id === f.suite)?.name ?? `#${f.suite}`;
    out.push({ key: "suite", name: "Suite", value: name, title: LINKED_ONLY });
  }
  return out;
}

/** "9 Sep – 8 Oct 2026": shared with the Test cases list's period filter. */
export { formatPeriod } from "../../lib/period";
