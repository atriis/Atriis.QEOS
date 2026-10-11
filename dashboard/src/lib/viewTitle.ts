/** Names of a project's views, shared by the document title, the breadcrumb and the rail. */
export const VIEW_TITLES: Record<string, string> = {
  overview: "Overview", trends: "Trends", tests: "Test results", flaky: "Flaky", branches: "Branches",
  runs: "Runs", report: "Report", settings: "Settings", cases: "Test cases", suites: "Suites",
};

/** The part of a project path after /projects/:id/, e.g. "runs/7". */
export function projectRest(pathname: string): string {
  return pathname.split("/").slice(3).join("/");
}

/** "runs/7" -> "Run #7", "tests/<key>" -> "Test history", "flaky" -> "Flaky" */
export function viewTitle(rest: string): string {
  const [view, detail, sub, other] = rest.split("/");
  if (view === "runs" && detail === "requested") return "Requested runs";
  if (view === "runs" && detail && sub === "compare" && other) return `Run #${detail} vs #${other}`;
  if (view === "runs" && detail) return `Run #${detail}`;
  if (view === "tests" && detail) return "Test history";
  if (view === "cases" && detail === "new") return "New test case";
  if (view === "cases" && detail === "import") return "Import from Gherkin";
  if (view === "cases" && detail === "feature") return "Feature";
  if (view === "cases" && detail) return `TC-${detail}`;
  if (view === "suites" && detail) return "Suite";
  return VIEW_TITLES[view] ?? "Project";
}

/** The view a detail page belongs to ("runs/7" -> runs), or null on a view's own page. */
export function parentView(rest: string): { view: string; label: string } | null {
  const [view, detail] = rest.split("/");
  if (!detail || !(view in VIEW_TITLES)) return null;
  return { view, label: VIEW_TITLES[view] };
}
