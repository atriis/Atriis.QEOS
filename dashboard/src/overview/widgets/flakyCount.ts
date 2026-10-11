import { lazy } from "react";
import { viewLink } from "../links";
import type { WidgetDefinition } from "./types";

export const flakyCount: WidgetDefinition = {
  type: "flaky_count",
  title: "Flaky tests",
  description: "Confirmed and suspected flaky tests over 7, 14 or 30 days.",
  defaultSize: "normal",
  settings: ["period"],
  defaults: { period: 14 },
  cardTitle: (settings) => `Flaky tests, last ${settings.period ?? 14} days`,
  Component: lazy(() => import("./FlakyCountWidget")),
  // The Flaky view's own default window (14) stays out of the URL
  link: (projectId, settings) =>
    viewLink(`/projects/${projectId}/flaky`, (settings.period ?? 14) === 14 ? {} : { window: String(settings.period) }, undefined),
};
