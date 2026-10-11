import { lazy } from "react";
import type { TrendBucket } from "../../api/analytics";
import { viewLink } from "../links";
import type { WidgetDefinition } from "./types";

/** Days asked per view: the Trends view's own choices (plan Ruling 15), so the title link opens the same chart from the
 *  cache. */
export const TREND_DAYS: Record<TrendBucket, number> = { day: 30, week: 90, month: 90 };

export const passRateTrend: WidgetDefinition = {
  type: "pass_rate_trend",
  title: "Pass-rate trend",
  description: "The pass rate per day, week or month, on all branches or one.",
  defaultSize: "wide",
  settings: ["granularity", "branch"],
  // No branch: every branch
  defaults: { granularity: "week" },
  Component: lazy(() => import("./PassRateTrendWidget")),
  link: (projectId, settings) => {
    const bucket = settings.granularity ?? "week";
    return viewLink(`/projects/${projectId}/trends`, { days: String(TREND_DAYS[bucket]), bucket }, settings.branch);
  },
  // The Trends view's queries (trendsViewQuery)
  staleKeys: (projectId) => [["trends", projectId]],
};
