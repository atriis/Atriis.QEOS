import type { LatestResult } from "../api/analytics";
import { ago } from "../overview/format";
import StatusDot from "./StatusDot";

/** A test's latest result as a badge: the status word with its dot, and how long ago. */
export default function LastResultPill({ result }: { result: LatestResult | null | undefined }) {
  if (!result) return <span className="badge badge-muted">No runs yet</span>;
  const label = result.status.charAt(0).toUpperCase() + result.status.slice(1);
  return <span className="badge"><StatusDot status={result.status} label={label} /> · {ago(result.started_at)}</span>;
}
