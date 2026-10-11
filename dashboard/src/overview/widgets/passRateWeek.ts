import { lazy } from "react";
import { viewLink } from "../links";
import type { WidgetDefinition } from "./types";

export const passRateWeek: WidgetDefinition = {
  type: "pass_rate_week",
  title: "Pass rate this week",
  description: "This week's pass rate against last week's.",
  defaultSize: "normal",
  settings: ["branch"],
  // No branch: every branch
  defaults: {},
  Component: lazy(() => import("./PassRateWeekWidget")),
  link: (projectId, settings) => viewLink(`/projects/${projectId}/trends`, { bucket: "week" }, settings.branch),
};
