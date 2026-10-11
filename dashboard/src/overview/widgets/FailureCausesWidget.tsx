import { formatCount } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import EmptyBranch from "../EmptyBranch";
import { useWidgetReport } from "../reportWidget";
import ReportFoot from "./ReportFoot";
import { failureCauses } from "./failureCauses";
import type { WidgetProps } from "./types";

const SHOWN = 5;

/** The Report's failure causes for the period: how many, new against recurring, resolved, and the top causes. */
export default function FailureCausesWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const period = settings.period ?? 30;
  const query = useWidgetReport(projectId, "failure_causes", period, settings.branch);
  const section = query.data?.failure_causes;
  const emptyBranch = settings.branch !== undefined && query.data?.scope.runs === 0;
  const groups = section?.groups ?? [];
  const fresh = groups.filter((g) => g.status === "new").length;
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStat label="Loading failure causes…" />}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {emptyBranch && <EmptyBranch branch={settings.branch!} days={period} onOpenSettings={onOpenSettings} />}
      {section && !emptyBranch && section.failures === 0 && <p className="muted">No failures in the last {period} days.</p>}
      {section && !emptyBranch && section.failures > 0 && (
        <>
          <p className="muted">{formatCount(section.failures)} failures from {formatCount(section.groups_total)} causes</p>
          <p className="muted">{fresh} new · {groups.length - fresh} recurring among the top {groups.length} · {formatCount(section.resolved.length)} resolved</p>
          <ul className="fail-list">
            {groups.slice(0, SHOWN).map((g) => (
              <li key={g.signature}>
                <span className="cause-title">
                  {g.status === "new" && <span className="badge badge-new">New</span>}
                  {g.headline ? <span className="msg">{g.headline}</span> : <span className="where">No error message</span>}
                </span>
                <span className="where">{formatCount(g.occurrences)} {g.occurrences === 1 ? "failure" : "failures"} in {formatCount(g.runs)} {g.runs === 1 ? "run" : "runs"}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <ReportFoot to={failureCauses.link(projectId, settings)} />
    </>
  );
}
