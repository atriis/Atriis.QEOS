import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const branchHealth: WidgetDefinition = {
  type: "branch_health",
  title: "Branch health",
  description: "Each branch's pass rate, runs and last run over 30 days.",
  defaultSize: "normal",
  settings: ["rows"],
  defaults: { rows: 5 },
  Component: lazy(() => import("./BranchHealthWidget")),
  link: (projectId) => `/projects/${projectId}/branches`,
  // The Branches view's query (branchesViewQuery)
  staleKeys: (projectId) => [["branches", projectId]],
};
