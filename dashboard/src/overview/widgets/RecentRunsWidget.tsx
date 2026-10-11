import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatCount } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { runVerdict } from "../../components/RunStatusBadge";
import { SkeletonStat } from "../../components/Skeleton";
import { RunVerdictPill } from "../../components/StatusPill";
import { runsFirstPageQuery } from "../../lib/runQueries";
import EmptyBranch from "../EmptyBranch";
import { ago } from "../format";
import { recentRuns } from "./recentRuns";
import type { WidgetProps } from "./types";

/** The newest runs with their verdicts in words, from the Runs view's first page (polled every 30 s). */
export default function RecentRunsWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const runs = useQuery(runsFirstPageQuery(projectId, settings.branch === undefined ? {} : { branch: settings.branch }));
  const list = runs.data ?? [];
  return (
    <>
      {heading}
      {runs.isPending && <SkeletonStat label="Loading recent runs…" />}
      {runs.error != null && <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />}
      {runs.data && list.length === 0 && (settings.branch === undefined
        ? <p className="muted">No runs yet.</p>
        : <EmptyBranch branch={settings.branch} onOpenSettings={onOpenSettings} />)}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.slice(0, rows).map((run) => (
            <li key={run.id}>
              <span className="cause-title">
                <RunVerdictPill verdict={runVerdict(run)} /> <Link to={`/projects/${projectId}/runs/${run.id}`}>Run #{run.id}</Link>
              </span>
              <span className="where">
                {run.branch ?? "no branch"} · {ago(run.started_at)} · {formatCount(run.passed)} passed, {formatCount(run.failed)} failed
                {run.errored > 0 && `, ${formatCount(run.errored)} errored`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={recentRuns.link(projectId, settings)}>Runs <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
