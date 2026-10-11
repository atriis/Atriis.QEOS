import { Link } from "react-router-dom";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import EmptyBranch from "../EmptyBranch";
import { formatDay } from "../format";
import { useWidgetReport } from "../reportWidget";
import ReportFoot from "./ReportFoot";
import { regressions } from "./regressions";
import type { WidgetProps } from "./types";

/** The Report's regressions for the period: newly failing, fixed, flips, and the newly failing tests. */
export default function RegressionsWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const period = settings.period ?? 30;
  const rows = settings.rows ?? 5;
  const query = useWidgetReport(projectId, "regressions", period, settings.branch);
  const section = query.data?.regressions;
  const emptyBranch = settings.branch !== undefined && query.data?.scope.runs === 0;
  const flips = section?.flakiness.reduce((sum, day) => sum + day.flips, 0) ?? 0;
  const items = section?.newly_failing.items ?? [];
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStat label="Loading regressions…" />}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {emptyBranch && <EmptyBranch branch={settings.branch!} days={period} onOpenSettings={onOpenSettings} />}
      {section && !emptyBranch && (
        <>
          <p className="muted">{section.newly_failing.total} newly failing · {section.fixed.total} fixed · {flips} flips</p>
          {items.length === 0 ? (
            <p className="muted">Nothing started failing in the last {period} days.</p>
          ) : (
            <ul className="fail-list">
              {items.slice(0, rows).map((item) => (
                <li key={`${item.test_key}-${item.branch ?? ""}`}>
                  <span><Link to={`/projects/${projectId}/tests/${encodeURIComponent(item.test_key)}`}>{item.name}</Link></span>
                  <span className="where">{item.branch ?? "no branch"} · failing since {formatDay(item.failing_since)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <ReportFoot to={regressions.link(projectId, settings)} />
    </>
  );
}
