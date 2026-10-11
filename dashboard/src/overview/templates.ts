import type { StoredLayout } from "./catalog";

/** What the Overview shows when neither a personal layout nor a project default exists: today's four cards
 *  (spec §2.1). The API answers `effective: null` in that case; the dashboard holds this layout. The pass-rate card
 *  has no `branch` setting, which means every branch. */
export const BUILTIN_DEFAULT: StoredLayout = {
  schema: 1,
  widgets: [
    { id: "w1", type: "latest_run", size: "wide", settings: {} },
    { id: "w2", type: "failing_now", size: "normal", settings: { rows: 5 } },
    { id: "w3", type: "pass_rate_week", size: "normal", settings: {} },
    { id: "w4", type: "flaky_count", size: "normal", settings: { period: 14 } },
  ],
};

export interface LayoutTemplate {
  name: "qa_lead" | "developer" | "flaky_hunt";
  label: string;
  layout: StoredLayout;
}

/** Ready layouts offered by Add widget (spec §2.5). Choosing one replaces the draft; Cancel still undoes it. No widget
 *  has a `branch` setting, which means every branch. */
export const TEMPLATES: LayoutTemplate[] = [
  {
    name: "qa_lead",
    label: "QA lead",
    layout: { schema: 1, widgets: [
      { id: "w1", type: "pass_rate_trend", size: "wide", settings: { granularity: "week" } },
      { id: "w2", type: "failure_causes", size: "normal", settings: { period: 30 } },
      { id: "w3", type: "regressions", size: "normal", settings: { period: 30, rows: 5 } },
      { id: "w4", type: "coverage", size: "normal", settings: { period: 30 } },
      { id: "w5", type: "case_tiles", size: "wide", settings: {} },
    ] },
  },
  {
    name: "developer",
    label: "Developer",
    layout: { schema: 1, widgets: [
      { id: "w1", type: "latest_run", size: "wide", settings: {} },
      { id: "w2", type: "failing_now", size: "normal", settings: { rows: 5 } },
      { id: "w3", type: "branch_health", size: "normal", settings: { rows: 5 } },
      { id: "w4", type: "recent_runs", size: "normal", settings: { rows: 5 } },
      { id: "w5", type: "my_failures", size: "normal", settings: { rows: 5 } },
    ] },
  },
  {
    name: "flaky_hunt",
    label: "Flaky hunt",
    layout: { schema: 1, widgets: [
      { id: "w1", type: "flaky_count", size: "normal", settings: { period: 30 } },
      { id: "w2", type: "regressions", size: "normal", settings: { period: 30, rows: 10 } },
      { id: "w3", type: "slowest_tests", size: "normal", settings: { period: 30, rows: 5 } },
      { id: "w4", type: "pass_rate_trend", size: "wide", settings: { granularity: "day" } },
    ] },
  },
];
