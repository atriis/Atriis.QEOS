/** Periods shared by the Report and the Test cases list (spec: Filters): presets of whole days ending today, or a
 *  custom From–To range of calendar days (YYYY-MM-DD), checked the same way everywhere. */

export const PRESETS = ["7", "30", "90"] as const;
export type Preset = (typeof PRESETS)[number];
export const MAX_SPAN_DAYS = 90;
export const MAX_AGE_DAYS = 400;

const DAY_MS = 86_400_000;

/** The calendar day it is now in `tz`, as YYYY-MM-DD. */
export function todayIn(tz: string, now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

export function addDays(day: string, n: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + n * DAY_MS).toISOString().slice(0, 10);
}

/** Days from `from` to `to`, both included. */
export function spanDays(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS) + 1;
}

export function isDay(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const time = Date.parse(`${s}T00:00:00Z`);
  return !Number.isNaN(time) && new Date(time).toISOString().slice(0, 10) === s;
}

// Fixed names: Intl's en-GB says "Sept" in newer ICU, and the period must read the same everywhere
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "9 Sep – 8 Oct 2026"; the year is repeated only when the range crosses one. These are calendar days (YYYY-MM-DD). */
export function formatPeriod(from: string, to: string): string {
  const [fy, fm, fd] = from.split("-").map(Number);
  const [ty, tm, td] = to.split("-").map(Number);
  const left = `${fd} ${MONTHS[fm - 1]}${fy === ty ? "" : ` ${fy}`}`;
  return `${left} – ${td} ${MONTHS[tm - 1]} ${ty}`;
}

export type RangeField = "from" | "to";
export interface RangeProblem { message: string; fields: RangeField[] }

/** Why a custom range cannot be applied, or null: both dates, in order, at most MAX_SPAN_DAYS long, not after
 *  today, not older than MAX_AGE_DAYS. The same check the URL reader applies. */
export function checkRange(from: string, to: string, today: string): RangeProblem | null {
  const both: RangeField[] = ["from", "to"];
  if (!from || !to) return { message: "Give both From and To", fields: [from ? "to" : "from"] };
  if (!isDay(from) || !isDay(to)) return { message: "Dates must be calendar days", fields: [isDay(from) ? "to" : "from"] };
  if (from > to) return { message: "From must be on or before To", fields: both };
  if (spanDays(from, to) > MAX_SPAN_DAYS) return { message: `The period can be at most ${MAX_SPAN_DAYS} days`, fields: both };
  if (to > today) return { message: "To cannot be after today", fields: ["to"] };
  if (from < addDays(today, -MAX_AGE_DAYS)) return { message: `From can be at most ${MAX_AGE_DAYS} days ago`, fields: ["from"] };
  return null;
}

/** The calendar days a preset covers: the last N days ending today. */
export function presetRange(preset: Preset, today: string): { from: string; to: string } {
  return { from: addDays(today, -(Number(preset) - 1)), to: today };
}

/** The instant a local calendar day starts, as a UTC ISO string; `plusDays` 1 gives the start of the next day, so a
 *  "to" day read as inclusive becomes an exclusive upper bound. */
export function dayStartIso(day: string, plusDays = 0): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
}
