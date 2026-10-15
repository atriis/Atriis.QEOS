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

const PLACEHOLDER = "{value}";

/** The link for a value from its pattern's template, or null. Checked again here, whatever the server stored: only
 *  an https template with a host, no credentials and {value} once after the host. The value is URL-encoded, so it
 *  cannot change the host or the path's structure; "." and ".." (a path segment that would move up) get no link. */
export function linkFor(template: string | null | undefined, value: string): string | null {
  if (!template || template.split(PLACEHOLDER).length !== 2 || value === "." || value === "..") return null;
  // {value} must come after the host: "https://" + host, then a "/", "?" or "#", before it
  if (!/^https:\/\/[^/?#]+[/?#]/i.test(template.slice(0, template.indexOf(PLACEHOLDER)))) return null;
  let base: URL;
  let built: URL;
  try {
    base = new URL(template.replace(PLACEHOLDER, "x"));
    built = new URL(template.replace(PLACEHOLDER, encodeURIComponent(value)));
  } catch {
    return null;
  }
  if (base.protocol !== "https:" || !base.hostname || base.username || base.password) return null;
  return built.origin === base.origin ? built.href : null;
}
