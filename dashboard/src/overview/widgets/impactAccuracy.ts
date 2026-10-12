import { lazy } from "react";
import { impactAccuracyStaleKeys } from "../../lib/impactQueries";
import { reportLink } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const impactAccuracy: WidgetDefinition = {
  type: "impact_accuracy",
  title: "Impact accuracy",
  description: "How often the likely affected tests suggested for a change contained its new failures, over 7, 14 or 30 days.",
  defaultSize: "normal",
  settings: ["period"],
  defaults: { period: 30 },
  cardTitle: (settings) => `Impact accuracy, last ${settings.period ?? 30} days`,
  Component: lazy(() => import("./ImpactAccuracyWidget")),
  // Every branch: the figure does not follow a branch (plan Ruling 21)
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, undefined, "report-impact"),
  staleKeys: impactAccuracyStaleKeys,
};
