import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const failingNow: WidgetDefinition = {
  type: "failing_now",
  title: "Failing in latest run",
  description: "The latest run's failures grouped by cause, new causes marked.",
  defaultSize: "normal",
  settings: ["rows"],
  defaults: { rows: 5 },
  Component: lazy(() => import("./FailingNowWidget")),
  // The run's own page is the card foot's link; the title opens every run with failures (plan Ruling 19)
  link: (projectId) => `/projects/${projectId}/runs?status=failing`,
};
