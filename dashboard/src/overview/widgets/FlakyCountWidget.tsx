import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import type { FlakyRow } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { FLAKY_DEFAULTS, flakyHealthQuery, flakyWindowQuery } from "../../lib/healthQueries";
import type { WidgetProps } from "./types";

/** Confirmed and suspected flaky tests over the window (today's card at 14 days). */
export default function FlakyCountWidget({ projectId, settings, heading }: WidgetProps) {
  const period = settings.period ?? FLAKY_DEFAULTS.windowDays;
  // 14 days is the Cases tile's query (quarantined tests included, counted out here); other windows are the Flaky view's
  const source = period === FLAKY_DEFAULTS.windowDays ? flakyHealthQuery(projectId) : flakyWindowQuery(projectId, period);
  const flaky = useQuery<FlakyRow[]>({ queryKey: source.queryKey, queryFn: source.queryFn, staleTime: source.staleTime });
  const unmuted = flaky.data?.filter((r) => !r.muted) ?? [];
  const confirmed = unmuted.filter((r) => r.reason === "same_commit").length;
  const suspected = unmuted.filter((r) => r.reason === "flips").length;
  return (
    <>
      {heading}
      {flaky.isPending && <SkeletonStat label="Loading flaky tests…" />}
      {flaky.error != null && <ErrorBanner error={flaky.error} onRetry={() => flaky.refetch()} />}
      {flaky.data && (
        <>
          <div className="stat-big">{confirmed + suspected}</div>
          <p className="muted">{confirmed} confirmed · {suspected} suspected</p>
        </>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={`/projects/${projectId}/flaky`}>Flaky tests <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
