import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const caseTiles: WidgetDefinition = {
  type: "case_tiles",
  title: "Test cases",
  description: "The Cases tiles: cases, pass rate, failing linked cases and flaky tests.",
  // Four tiles need the row (plan Ruling 29)
  defaultSize: "wide",
  settings: [],
  defaults: {},
  Component: lazy(() => import("./CaseTilesWidget")),
  link: (projectId) => `/projects/${projectId}/cases`,
  // The tiles' run-dependent queries (CasesKpis): the week's pass rate, flaky tests, and the failing-cases join.
  // The case totals follow test management, not runs
  staleKeys: (projectId) => [
    ["trends", projectId, "overview-weeks"], ["flaky", projectId, "health"], ["latest-keys", projectId], ["cases-search", projectId],
  ],
};
