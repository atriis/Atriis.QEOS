import type { TrendBucket } from "../api/analytics";

/** "YYYY-MM-DD" as that local calendar day (new Date("2026-03-04") would be UTC midnight and can read as the day before). */
function parseDay(date: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/** What one point stands for, as a word: "day", "week" or "month". */
export const bucketUnit = (bucket: TrendBucket): string => bucket;

/** A short axis tick: "Mar 4" for days and weeks, "Mar 26" (month and year) for months. */
export function formatTick(date: string, bucket: TrendBucket = "day"): string {
  const d = parseDay(date);
  if (!d) return date;
  return new Intl.DateTimeFormat(undefined, bucket === "month" ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" }).format(d);
}

/** The full label for a point: a weekday and date, "Week of ..." for weeks, month and year for months. */
export function formatPointLabel(date: string, bucket: TrendBucket = "day"): string {
  const d = parseDay(date);
  if (!d) return date;
  if (bucket === "month") return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(d);
  const day = new Intl.DateTimeFormat(undefined, { weekday: bucket === "day" ? "short" : undefined, year: "numeric", month: "short", day: "numeric" }).format(d);
  return bucket === "week" ? `Week of ${day}` : day;
}

/** Axis tick text: Graphite at 12px (DESIGN.md Chart Textures). */
export const AXIS_TICK = { fill: "var(--text-secondary)", fontSize: 12 } as const;

/** The Recharts tooltip on the card surface. */
export const TOOLTIP_STYLES = {
  contentStyle: { background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 },
  itemStyle: { color: "var(--text-primary)" },
  labelStyle: { color: "var(--text-secondary)" },
} as const;
