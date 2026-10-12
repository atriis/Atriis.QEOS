import { formatCount } from "../api/analytics";

/** A count with its noun: "1 test", "1,234 runs" (the locale's grouping). */
export const plural = (n: number, one: string, many: string): string => `${formatCount(n)} ${n === 1 ? one : many}`;

/** A test's history page, on `branch` when one is given. */
export function testHistoryPath(projectId: number | string, testKey: string, branch?: string | null): string {
  const path = `/projects/${projectId}/tests/${encodeURIComponent(testKey)}`;
  return branch ? `${path}?branch=${encodeURIComponent(branch)}` : path;
}
