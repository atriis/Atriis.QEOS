import { Link } from "react-router-dom";
import type { StripRun, StripStatus } from "../api/analytics";
import { dateFormat } from "../lib/words";

export type { StripRun, StripStatus };

const WORD: Record<"passed" | "failed" | "rerun" | "skipped" | "none", string> = {
  passed: "passed",
  failed: "failed",
  rerun: "re-run",
  skipped: "skipped",
  none: "not run",
};
const ORDER = ["passed", "failed", "rerun", "skipped", "none"] as const;

export function stripSummary(statuses: StripStatus[]): string {
  const parts = ORDER.flatMap((k) => {
    const n = statuses.filter((s) => (s ?? "none") === k).length;
    return n > 0 ? [`${n} ${WORD[k]}`] : [];
  });
  return `Last ${statuses.length} ${statuses.length === 1 ? "run" : "runs"}: ${parts.join(", ")}`;
}

export default function RunStrip({ projectId, runs, statuses }: { projectId: number; runs: StripRun[]; statuses: StripStatus[] }) {
  if (runs.length === 0) return <span className="muted">No runs yet</span>;
  const summary = stripSummary(statuses);
  const labels = runs.map((run, i) => `Run #${run.id}, ${dateFormat.format(new Date(run.started_at))}: ${WORD[statuses[i] ?? "none"]}`);
  const bars = runs.map((run, i) => <span key={run.id} className={`run-bar bar-${statuses[i] ?? "none"}`} title={labels[i]} aria-hidden="true" />);
  // Runs arrive oldest to newest, so the newest run the test was in is the last non-null status.
  const newest = [...runs].reverse().find((_, i) => statuses[runs.length - 1 - i] != null);
  if (!newest) {
    return <div className="run-strip" role="img" aria-label={summary}>{bars}</div>;
  }
  // The per-run list sits after the link: inside it, the link's aria-label would hide it from screen readers.
  return (
    <>
      <Link className="run-strip" to={`/projects/${projectId}/runs/${newest.id}`} aria-label={`${summary}, opens run #${newest.id}`}>
        {bars}
      </Link>
      <ol className="sr-only">{labels.map((l, i) => <li key={runs[i].id}>{l}</li>)}</ol>
    </>
  );
}

export function RunStripSkeleton() {
  return (
    <div className="run-strip">
      {Array.from({ length: 10 }, (_, i) => <span key={i} className="run-bar bar-loading" aria-hidden="true" />)}
      <span className="sr-only">Loading last runs</span>
    </div>
  );
}
