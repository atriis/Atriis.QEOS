import { lazy } from "react";
import { runsPagesStaleKey } from "../../lib/runQueries";
import { viewLink } from "../links";
import type { WidgetDefinition } from "./types";

export const recentRuns: WidgetDefinition = {
  type: "recent_runs",
  title: "Recent runs",
  description: "The newest runs with their verdicts, on all branches or one.",
  defaultSize: "normal",
  settings: ["branch", "rows"],
  // No branch: every branch
  defaults: { rows: 5 },
  Component: lazy(() => import("./RecentRunsWidget")),
  link: (projectId, settings) => viewLink(`/projects/${projectId}/runs`, {}, settings.branch),
  // Polled too, but a new run refreshes it at once, beside Latest run
  staleKeys: (projectId) => [runsPagesStaleKey(projectId)],
};
