import { useRef, useState, type KeyboardEvent } from "react";
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

/** A test's own last results, oldest to newest: only runs it was in, so there are no gaps. Each bar is a link to its
 *  run (or to `href(run)`: the case or feature as of that run); the strip is one tab stop, arrow keys move between bars. */
export default function RunStrip({ projectId, entries, href }: {
  projectId: number;
  entries: StripEntry[];
  href?: (runId: number) => string;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const links = useRef<(HTMLAnchorElement | null)[]>([]);
  if (entries.length === 0) return <span className="muted">No runs yet</span>;
  const last = entries.length - 1;
  // The newest run is the tab stop until another bar takes focus
  const active = picked == null ? last : Math.min(picked, last);
  const to = href ?? ((runId: number) => `/projects/${projectId}/runs/${runId}`);
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = { ArrowLeft: active - 1, ArrowRight: active + 1, Home: 0, End: last }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const index = Math.max(0, Math.min(last, next));
    setPicked(index);
    links.current[index]?.focus();
  };
  return (
    <div className="run-strip" role="group" aria-label={stripSummary(entries.map((e) => e.status))} onKeyDown={move}>
      {entries.map((e, i) => {
        const label = `Run #${e.run_id}, ${dateFormat.format(new Date(e.started_at))}: ${WORD[e.status]}`;
        return (
          <Link key={e.run_id} className="run-bar-link" to={to(e.run_id)} aria-label={label} title={label}
            tabIndex={i === active ? 0 : -1} onFocus={() => setPicked(i)}
            ref={(el) => { links.current[i] = el; }}>
            <span className={`run-bar bar-${e.status}`} aria-hidden="true" />
          </Link>
        );
      })}
    </div>
  );
}

/** While the strips load: the strip's space is kept (no row jumps) but stays empty, so paging never flashes grey bars. */
export function RunStripSkeleton() {
  return (
    <div className="run-strip">
      <span className="sr-only">Loading last runs</span>
    </div>
  );
}
