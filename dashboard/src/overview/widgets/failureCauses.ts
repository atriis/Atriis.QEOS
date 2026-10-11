import { lazy } from "react";
import { reportLink, reportStaleKeys } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const failureCauses: WidgetDefinition = {
  type: "failure_causes",
  title: "Failure causes",
  description: "Failures grouped by cause over a period: new, recurring and resolved.",
  defaultSize: "normal",
  settings: ["period", "branch"],
  // No branch: every branch (plan Ruling 16)
  defaults: { period: 30 },
  Component: lazy(() => import("./FailureCausesWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, settings.branch, "report-causes"),
  staleKeys: reportStaleKeys("failure_causes"),
};
