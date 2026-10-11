import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const latestRun: WidgetDefinition = {
  type: "latest_run",
  title: "Latest run",
  description: "The newest run's verdict, commit, branch and counts.",
  defaultSize: "wide",
  settings: [],
  defaults: {},
  Component: lazy(() => import("./LatestRunWidget")),
  link: (projectId) => `/projects/${projectId}/runs`,
};
