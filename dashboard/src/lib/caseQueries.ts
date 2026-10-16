import { type KeysWindow, getLatestKeys } from "../api/analytics";
import { searchCases, type CaseSearchBody } from "../api/cases";

/** A page of the Cases list. */
export const CASES_PAGE = 50;
/** The latest-result join is re-asked at most once a minute: the list's filter and the Failing tile share it. */
const JOIN_STALE_MS = 60_000;

/** Test keys whose latest result has `status`, under one key for every reader (list filter, Failing tile). */
export const latestKeysQuery = (projectId: number, status: "passed" | "failed" | "skipped" | "any", window?: KeysWindow) => ({
  queryKey: ["latest-keys", projectId, status, window?.since ?? "", window?.until ?? ""] as const,
  queryFn: () => getLatestKeys(projectId, status, window),
  staleTime: JOIN_STALE_MS,
});

/** A case search with resolved test keys, keyed by its body: the same body is one request. */
export const caseSearchQuery = (projectId: number, body: CaseSearchBody) => ({
  queryKey: ["cases-search", projectId, body] as const,
  queryFn: () => searchCases(projectId, body),
  staleTime: JOIN_STALE_MS,
});

/** The body of the Cases list with only the Failing filter applied, on its first page: the Failing tile counts with
 *  exactly this, so its number is that list's total and opening it costs no new request. */
export const failingSearchBody = (keys: string[]): CaseSearchBody => ({
  labels: [], test_keys: keys, keys_mode: "include", limit: CASES_PAGE, offset: 0,
});
