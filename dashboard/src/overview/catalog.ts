import raw from "../../../shared/qeos_shared/overview_widgets.json";
import type { TrendBucket } from "../api/analytics";

/** The Overview widget catalogue, shared with project-service (spec 2026-10-11 §3.2): the types, their settings and
 *  allowed values, and the layout limits. project-service validates saved layouts against the same file; the
 *  dashboard does not re-validate a layout, it only skips types it does not know. The Dockerfile copies the file. */

export type WidgetSize = "normal" | "wide";
export type SettingName = "rows" | "period" | "granularity" | "branch" | "author";
export type WidgetType =
  | "latest_run" | "failing_now" | "pass_rate_week" | "flaky_count" | "pass_rate_trend" | "failure_causes"
  | "regressions" | "recent_runs" | "branch_health" | "slowest_tests" | "coverage" | "case_tiles"
  | "my_failures" | "my_suites";

export interface ChoiceSetting { kind: "choice"; values: (string | number)[] }
export interface TextSetting { kind: "text"; min_length: number; max_length: number }
export type SettingSpec = ChoiceSetting | TextSetting;

export interface Catalog {
  schema: number;
  max_widgets: number;
  max_body_bytes: number;
  widget_id_pattern: string;
  sizes: WidgetSize[];
  settings: Record<SettingName, SettingSpec>;
  types: Record<WidgetType, { settings: SettingName[] }>;
}

export const CATALOG = raw as unknown as Catalog;
export const MAX_WIDGETS = CATALOG.max_widgets;

/** A widget's settings. An absent `branch` means every branch: there is no "all" value, so a git branch named
 *  `all` stays selectable. */
export interface WidgetSettings {
  rows?: number;
  period?: number;
  granularity?: TrendBucket;
  branch?: string;
  author?: string;
}

/** A widget as stored: `type` is a string because a stored layout may name a type this dashboard does not know. */
export interface StoredWidget {
  id: string;
  type: string;
  size: WidgetSize;
  settings?: WidgetSettings;
}

export interface StoredLayout {
  schema: number;
  widgets: StoredWidget[];
}

/** Whether one setting value is allowed, so a stored value the catalogue no longer allows falls back to the default. */
export function isValidSetting(name: SettingName, value: unknown): boolean {
  const spec = CATALOG.settings[name];
  if (spec.kind === "choice") return spec.values.some((allowed) => allowed === value);
  return typeof value === "string" && value.length >= spec.min_length && value.length <= spec.max_length && !value.includes("\u0000");
}
