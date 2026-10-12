import { formatCount } from "../api/analytics";

/** A run's start as the run strip and the impact misses say it: "10 Oct, 09:00" in the reader's locale. */
export const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** A count with its noun: "1 test", "1,234 runs" (the locale's grouping). */
export const plural = (n: number, one: string, many: string): string => `${formatCount(n)} ${n === 1 ? one : many}`;

/** A test's history page, on `branch` when one is given. */
export function testHistoryPath(projectId: number | string, testKey: string, branch?: string | null): string {
  const path = `/projects/${projectId}/tests/${encodeURIComponent(testKey)}`;
  return branch ? `${path}?branch=${encodeURIComponent(branch)}` : path;
}
