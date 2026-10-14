import { Link } from "react-router-dom";
import type { StripEntry, StripStatus } from "../api/analytics";
import { dateFormat } from "../lib/words";

export type { StripEntry, StripStatus };

const WORD: Record<StripStatus, string> = {
  passed: "passed",
  failed: "failed",
  rerun: "re-run",
  skipped: "skipped",
};
const ORDER = ["passed", "failed", "rerun", "skipped"] as const;

export function stripSummary(statuses: StripStatus[]): string {
  const parts = ORDER.flatMap((k) => {
    const n = statuses.filter((s) => s === k).length;
    return n > 0 ? [`${n} ${WORD[k]}`] : [];
  });
  return `Last ${statuses.length} ${statuses.length === 1 ? "run" : "runs"}: ${parts.join(", ")}`;
}

/** A test's own last results, oldest to newest: only runs it was in, so there are no gaps. */
export default function RunStrip({ projectId, entries }: { projectId: number; entries: StripEntry[] }) {
  if (entries.length === 0) return <span className="muted">No runs yet</span>;
  const summary = stripSummary(entries.map((e) => e.status));
  const labels = entries.map((e) => `Run #${e.run_id}, ${dateFormat.format(new Date(e.started_at))}: ${WORD[e.status]}`);
  const bars = entries.map((e, i) => <span key={e.run_id} className={`run-bar bar-${e.status}`} title={labels[i]} aria-hidden="true" />);
  const newest = entries[entries.length - 1];
  // The per-run list sits after the link: inside it, the link's aria-label would hide it from screen readers.
  return (
    <>
      <Link className="run-strip" to={`/projects/${projectId}/runs/${newest.run_id}`} aria-label={`${summary}, opens run #${newest.run_id}`}>
        {bars}
      </Link>
      <ol className="sr-only">{labels.map((l, i) => <li key={entries[i].run_id}>{l}</li>)}</ol>
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
