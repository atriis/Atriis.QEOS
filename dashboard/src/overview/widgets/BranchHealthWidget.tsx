import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatCount, formatPassRate } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { branchesViewQuery } from "../../lib/healthQueries";
import { ago } from "../format";
import { viewLink } from "../links";
import { branchHealth } from "./branchHealth";
import type { WidgetProps } from "./types";

/** Each branch's pass rate, runs and last run over 30 days, newest first: the Branches view's numbers (plan Ruling 14).
 *  No verdict per branch: the Branches API has none. */
export default function BranchHealthWidget({ projectId, settings, heading }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const branches = useQuery(branchesViewQuery(projectId));
  const list = [...(branches.data ?? [])].sort((a, b) => b.last_seen.localeCompare(a.last_seen)).slice(0, rows);
  return (
    <>
      {heading}
      {branches.isPending && <SkeletonStat label="Loading branch health…" />}
      {branches.error != null && <ErrorBanner error={branches.error} onRetry={() => branches.refetch()} />}
      {branches.data && list.length === 0 && <p className="muted">No runs in the last 30 days.</p>}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.map((b) => (
            <li key={b.branch ?? "(no branch)"}>
              <span>
                {b.branch
                  ? <Link to={viewLink(`/projects/${projectId}/runs`, {}, b.branch)}>{b.branch}</Link>
                  : <span className="where">No branch</span>}
              </span>
              <span className="where">
                {formatPassRate(b.pass_rate)} pass rate · {formatCount(b.runs)} {b.runs === 1 ? "run" : "runs"} · last {ago(b.last_seen)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={branchHealth.link(projectId, settings)}>Branches <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
