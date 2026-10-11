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
