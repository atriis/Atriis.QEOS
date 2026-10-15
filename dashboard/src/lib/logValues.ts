import type { LogValueGroup } from "../api/analytics";

/** The most values a tooltip line shows per pattern before "+N more" (spec §4.2). */
export const TOOLTIP_VALUES_MAX = 5;

/** One tooltip line per pattern with values: "trip_id: 3960562, 3960563"; the sixth and later as "+N more". */
export function valueLines(groups: LogValueGroup[] | undefined): string[] {
  return (groups ?? [])
    .filter((g) => g.values.length > 0)
    .map((g) => {
      const more = g.values.length - TOOLTIP_VALUES_MAX;
      return `${g.name}: ${g.values.slice(0, TOOLTIP_VALUES_MAX).join(", ")}${more > 0 ? ` +${more} more` : ""}`;
    });
}

/** Several results' values as one (a feature row's run): per pattern in name order, values in first-seen order,
 *  duplicates removed. */
export function mergeValues(lists: (LogValueGroup[] | undefined)[]): LogValueGroup[] {
  const byName = new Map<string, string[]>();
  for (const list of lists) {
    for (const group of list ?? []) {
      const values = byName.get(group.name) ?? [];
      for (const value of group.values) if (!values.includes(value)) values.push(value);
      byName.set(group.name, values);
    }
  }
  return [...byName.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, values]) => ({ name, values }));
}
