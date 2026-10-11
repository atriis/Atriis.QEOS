import { lazy } from "react";
import { reportLink, reportStaleKeys } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const coverage: WidgetDefinition = {
  type: "coverage",
  title: "Coverage",
  description: "Linked and manual cases, automated cases not run, and tests without a case.",
  defaultSize: "normal",
  settings: ["period"],
  defaults: { period: 30 },
  Component: lazy(() => import("./CoverageWidget")),
  // Across every branch (plan Ruling 13)
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, undefined, "report-coverage"),
  // The tests section; the case areas follow test management, not runs, so a new run leaves them as they are
  staleKeys: reportStaleKeys("tests"),
};
