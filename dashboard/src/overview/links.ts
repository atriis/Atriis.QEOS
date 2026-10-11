import { buildQuery } from "../api/http";

/** A widget's full-view link with the same filters (spec §2.7). A widget with no `branch` setting covers every branch:
 *  on views where no `branch` parameter already means every branch (Trends, Runs, Flaky) the link names none; the
 *  report reads no `branch` as the default branch, so its links pass `everyBranch` (its ALL_BRANCHES, `*`). */
export function viewLink(
  path: string,
  params: Record<string, string>,
  branch: string | undefined,
  { everyBranch }: { everyBranch?: string } = {},
): string {
  return `${path}${buildQuery({ ...params, branch: branch ?? everyBranch })}`;
}
