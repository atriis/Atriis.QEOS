import { lazy } from "react";
import { reportLink, reportStaleKeys } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const slowestTests: WidgetDefinition = {
  type: "slowest_tests",
  title: "Slowest tests",
  description: "The tests with the longest average duration over a period.",
  defaultSize: "normal",
  settings: ["period", "branch", "rows"],
  // No branch: every branch (plan Ruling 16)
  defaults: { period: 30, rows: 5 },
  Component: lazy(() => import("./SlowestTestsWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, settings.branch, "report-summary"),
  staleKeys: reportStaleKeys("summary"),
};
