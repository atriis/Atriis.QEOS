import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatCount } from "../../api/analytics";
import { listSuites } from "../../api/cases";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { mySuites, mySuitesQueryKey } from "./mySuites";
import type { WidgetProps } from "./types";

/** The suites the signed-in person created (test management's `created_by=me`). */
export default function MySuitesWidget({ projectId, settings, heading }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const suites = useQuery({ queryKey: mySuitesQueryKey(projectId), queryFn: () => listSuites(projectId, { createdBy: "me" }) });
  const list = suites.data ?? [];
  return (
    <>
      {heading}
      {suites.isPending && <SkeletonStat label="Loading your suites…" />}
      {suites.error != null && <ErrorBanner error={suites.error} onRetry={() => suites.refetch()} />}
      {suites.data && list.length === 0 && <p className="muted">You have not created a suite in this project yet.</p>}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.slice(0, rows).map((suite) => (
            <li key={suite.id}>
              <span><Link to={`/projects/${projectId}/suites/${suite.id}`}>{suite.name}</Link></span>
              <span className="where">{formatCount(suite.case_count)} {suite.case_count === 1 ? "case" : "cases"}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={mySuites.link(projectId, settings)}>Suites <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
