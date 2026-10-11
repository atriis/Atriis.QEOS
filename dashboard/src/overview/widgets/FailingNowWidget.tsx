import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import ErrorBanner from "../../components/ErrorBanner";
import { isNewCause } from "../../components/FailureGroups";
import { failureGroupsQuery, latestRunQuery } from "../queries";
import type { WidgetProps } from "./types";

/** The latest run's failures grouped by cause, new causes marked (today's card; `rows` causes, 5 by default). */
export default function FailingNowWidget({ projectId, settings, heading }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const runs = useQuery(latestRunQuery(projectId));
  const latest = runs.data?.[0];
  const causes = useQuery(failureGroupsQuery(latest));
  if (!latest) return <>{heading}</>;
  const broken = latest.failed + latest.errored;
  const groups = causes.data?.groups ?? [];
  return (
    <>
      {heading}
      {broken === 0 && <p className="muted">Nothing failed in the latest run.</p>}
      {broken > 0 && causes.isPending && <p className="muted">Loading failures…</p>}
      {causes.error != null && <ErrorBanner error={causes.error} onRetry={() => causes.refetch()} />}
      {groups.length > 0 && (
        <>
          <p className="muted">
            {causes.data!.total} {causes.data!.total === 1 ? "test" : "tests"} · {groups.length}{" "}
            {groups.length === 1 ? "cause" : "causes"}
          </p>
          <ul className="fail-list">
            {groups.slice(0, rows).map((g) => {
              const first = g.tests[0];
              return (
                <li key={g.signature}>
                  <span className="cause-title">
                    {isNewCause(g.history) && <span className="badge badge-new">New</span>}
                    {g.headline ? <span className="msg">{g.headline}</span> : <span className="where">No error message</span>}
                  </span>
                  <span>
                    <Link to={`/projects/${projectId}/tests/${encodeURIComponent(first.test_key)}`}>{first.name}</Link>
                    {g.count > 1 && <span className="where"> and {g.count - 1} more</span>}
                    {(g.quarantined ?? 0) > 0 && <span className="where"> · {g.quarantined === g.count ? "in quarantine" : `${g.quarantined} in quarantine`}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {broken > 0 && (groups.length > rows || groups.some((g) => g.count > 1)) && (
        <div className="card-foot">
          <Link className="link-arrow" to={`/projects/${projectId}/runs/${latest.id}`}>All {broken} failures by cause <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      )}
    </>
  );
}
