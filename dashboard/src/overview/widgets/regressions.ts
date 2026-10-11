import { lazy } from "react";
import { reportLink, reportStaleKeys } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const regressions: WidgetDefinition = {
  type: "regressions",
  title: "Regressions and flips",
  description: "Tests that started failing, tests fixed, and result flips over a period.",
  defaultSize: "normal",
  settings: ["period", "branch", "rows"],
  // No branch: every branch (plan Ruling 16)
  defaults: { period: 30, rows: 5 },
  Component: lazy(() => import("./RegressionsWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, settings.branch, "report-regressions"),
  staleKeys: reportStaleKeys("regressions"),
};
