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

export interface LogSegment { text: string; name?: string }

/** The log cut into plain text and marked values: each occurrence of a value becomes a segment named after its
 *  pattern; on overlap the longer value wins and nothing is marked inside a mark. Linear in the text: at each
 *  position only the values that start with that character are tried. */
export function markValues(text: string, groups: LogValueGroup[]): LogSegment[] {
  const byFirst = new Map<string, { value: string; name: string }[]>();
  for (const g of groups) {
    for (const value of g.values) {
      if (!value) continue;
      const list = byFirst.get(value[0]) ?? [];
      list.push({ value, name: g.name });
      byFirst.set(value[0], list);
    }
  }
  for (const list of byFirst.values()) list.sort((a, b) => b.value.length - a.value.length);
  if (byFirst.size === 0 || text === "") return [{ text }];
  const out: LogSegment[] = [];
  let plainFrom = 0;
  let i = 0;
  while (i < text.length) {
    const hit = byFirst.get(text[i])?.find((c) => text.startsWith(c.value, i));
    if (!hit) {
      i += 1;
      continue;
    }
    if (i > plainFrom) out.push({ text: text.slice(plainFrom, i) });
    out.push({ text: hit.value, name: hit.name });
    i += hit.value.length;
    plainFrom = i;
  }
  if (plainFrom < text.length) out.push({ text: text.slice(plainFrom) });
  return out;
}

/** "<test name>-run-<id>.txt" with anything outside letters, digits, dots, dashes and underscores as "_". */
export function logFileName(name: string, runId: number): string {
  const safe = name.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return `${safe || "result"}-run-${runId}.txt`;
}
