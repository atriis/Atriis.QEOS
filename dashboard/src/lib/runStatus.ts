import { formatDuration } from "../api/analytics";
import { RunRequest } from "../api/runRequests";
import { Run } from "../api/runs";

export type RunTone = "queued" | "running" | "passed" | "failed" | "cancelled" | "skipped" | "error";
export const RESULTS_WAIT_MS = 5 * 60_000;
/** Results are looked up from this long before the request, so clock skew never hides them. */
export const MATCH_SLACK_MS = 10 * 60_000;

export interface RunDescription {
  text: string;
  tone: RunTone;
  /** The text without anything that ticks (elapsed time): what a screen reader hears. Equal to `text` when nothing ticks. */
  liveText: string;
  /** A secondary line: why the request is stale ("GitHub: …"). */
  detail: string | null;
}

/** When the end of a request was seen: the later of stopped_at and checked_at; null when it has neither. */
export function seenEndAt(r: RunRequest): number | null {
  const times = [r.stopped_at, r.checked_at].map((t) => (t ? Date.parse(t) : NaN)).filter((t) => !Number.isNaN(t));
  return times.length > 0 ? Math.max(...times) : null;
}

/** The moment an ended request ended: seenEndAt, else requested_at. */
export function endedAt(r: RunRequest): number {
  return seenEndAt(r) ?? Date.parse(r.requested_at);
}

function describeState(r: RunRequest, nameOf: (id: number | null) => string, now: number): { text: string; tone: RunTone; liveText?: string } {
  switch (r.status) {
    case "queued":
      return { text: "Queued", tone: "queued" };
    case "running": {
      const tests = r.case_count === 1 ? "1 test" : `${r.case_count} tests`;
      const elapsed = formatDuration(Math.max(0, now - Date.parse(r.requested_at)));
      const started = `${tests} · started by ${nameOf(r.requested_by)}`;
      return { text: `Running · ${started} · ${elapsed}`, tone: "running", liveText: `In progress: ${tests}, requested by ${nameOf(r.requested_by)}` };
    }
    case "cancelling":
      return { text: "Stopping…", tone: "cancelled" };
    case "cancelled":
      if (r.stopped_by != null) return { text: `Stopped by ${nameOf(r.stopped_by)}`, tone: "cancelled" };
      return { text: r.error ? `Cancelled: ${r.error}` : "Cancelled", tone: "cancelled" };
    case "failed_to_start":
      return { text: `Didn't start: ${r.error ?? "unknown error"}`, tone: "error" };
    case "completed":
      if (r.conclusion === "success") return { text: "Passed", tone: "passed" };
      if (r.conclusion === "skipped") return { text: "Skipped", tone: "skipped" };
      return { text: "Failed", tone: "failed" };
  }
}

/** What a run request's state reads as, in the panel and in the Requested runs tab. */
export function describeRun(r: RunRequest, nameOf: (id: number | null) => string, now: number = Date.now()): RunDescription {
  const d = describeState(r, nameOf, now);
  // The stored error explains an active request that GitHub cannot be asked about; ended rows carry it in their text
  const active = r.status === "queued" || r.status === "running" || r.status === "cancelling";
  const detail = active && r.error ? (r.error.startsWith("GitHub") ? r.error : `GitHub: ${r.error}`) : null;
  return { text: d.text, tone: d.tone, liveText: d.liveText ?? d.text, detail };
}

/** The QEOS test run this request's GitHub run uploaded: same CI URL, ignoring case
 *  (GitHub may return owner/repo with different capitals). */
export function matchRun(runs: Run[], url: string | null): Run | undefined {
  if (!url) return undefined;
  const wanted = url.toLowerCase();
  return runs.find((r) => r.ci_run_url?.toLowerCase() === wanted);
}
