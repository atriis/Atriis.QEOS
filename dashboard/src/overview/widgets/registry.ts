import { CATALOG, type StoredLayout, type StoredWidget, type WidgetSettings, type WidgetType, isValidSetting } from "../catalog";
import { failingNow } from "./failingNow";
import { flakyCount } from "./flakyCount";
import { latestRun } from "./latestRun";
import { passRateWeek } from "./passRateWeek";
import type { WidgetDefinition } from "./types";

/** Widget type → definition. registry.test.ts fails when this and overview_widgets.json disagree. */
export const REGISTRY: Partial<Record<WidgetType, WidgetDefinition>> = {
  latest_run: latestRun,
  failing_now: failingNow,
  pass_rate_week: passRateWeek,
  flaky_count: flakyCount,
};

const warned = new Set<string>();

/** The definition, or undefined for a type this dashboard does not know (a layout saved by a newer version): such
 *  widgets are skipped, logged once per type (spec §4). */
export function definitionOf(type: string): WidgetDefinition | undefined {
  const def = Object.hasOwn(REGISTRY, type) ? REGISTRY[type as WidgetType] : undefined;
  if (def === undefined && !warned.has(type)) {
    warned.add(type);
    console.warn(`Overview: skipping widget type "${type}", which this dashboard does not know`);
  }
  return def;
}

export function knownWidgets(layout: StoredLayout): StoredWidget[] {
  return layout.widgets.filter((widget) => definitionOf(widget.type) !== undefined);
}

/** What Add widget offers, in catalogue order. */
export function addableDefinitions(): WidgetDefinition[] {
  return (Object.keys(CATALOG.types) as WidgetType[]).flatMap((type) => REGISTRY[type] ?? []);
}

/** The widget's defaults overlaid with each stored setting that is still valid. */
export function withDefaults(def: WidgetDefinition, stored: WidgetSettings | undefined): WidgetSettings {
  const out: Record<string, unknown> = { ...def.defaults };
  for (const name of def.settings) {
    const value = stored?.[name];
    if (value !== undefined && isValidSetting(name, value)) out[name] = value;
  }
  return out as WidgetSettings;
}

export function widgetTitle(widget: StoredWidget): string {
  const def = definitionOf(widget.type);
  if (def === undefined) return widget.type;
  return def.cardTitle ? def.cardTitle(withDefaults(def, widget.settings)) : def.title;
}
