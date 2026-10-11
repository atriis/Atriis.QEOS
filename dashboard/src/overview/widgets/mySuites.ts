import { lazy } from "react";
import type { WidgetDefinition } from "./types";

/** The widget's query: the caller's own suites. The Suites view invalidates `["suites", id]`, which covers this key. */
export const mySuitesQueryKey = (projectId: number) => ["suites", projectId, "mine"] as const;

export const mySuites: WidgetDefinition = {
  type: "my_suites",
  title: "My suites",
  description: "The suites you created in this project.",
  defaultSize: "normal",
  settings: ["rows"],
  defaults: { rows: 5 },
  Component: lazy(() => import("./MySuitesWidget")),
  link: (projectId) => `/projects/${projectId}/suites`,
  // Suites follow test management, not runs: a new run leaves them as they are
  staleKeys: () => [],
};
