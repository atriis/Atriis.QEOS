import { Link } from "react-router-dom";
import { formatDuration } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import EmptyBranch from "../EmptyBranch";
import { useWidgetReport } from "../reportWidget";
import ReportFoot from "./ReportFoot";
import { slowestTests } from "./slowestTests";
import type { WidgetProps } from "./types";

/** The tests with the longest average duration in the period: the summary's `slowest`, the per-test numbers the
 *  report computes (the duration section has no per-test rows; plan Ruling 12). */
export default function SlowestTestsWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const period = settings.period ?? 30;
  const rows = settings.rows ?? 5;
  const query = useWidgetReport(projectId, "summary", period, settings.branch);
  const emptyBranch = settings.branch !== undefined && query.data?.scope.runs === 0;
  const slowest = query.data?.summary?.slowest ?? [];
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStat label="Loading slowest tests…" />}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {emptyBranch && <EmptyBranch branch={settings.branch!} days={period} onOpenSettings={onOpenSettings} />}
      {query.data && !emptyBranch && slowest.length === 0 && <p className="muted">No tests ran in the last {period} days.</p>}
      {query.data && !emptyBranch && slowest.length > 0 && (
        <ol className="fail-list">
          {slowest.slice(0, rows).map((t) => (
            <li key={t.test_key}>
              <span><Link to={`/projects/${projectId}/tests/${encodeURIComponent(t.test_key)}`}>{t.name}</Link></span>
              <span className="where">{formatDuration(t.avg_duration_ms)} on average · {t.executions} {t.executions === 1 ? "run" : "runs"}</span>
            </li>
          ))}
        </ol>
      )}
      <ReportFoot to={slowestTests.link(projectId, settings)} />
    </>
  );
}
