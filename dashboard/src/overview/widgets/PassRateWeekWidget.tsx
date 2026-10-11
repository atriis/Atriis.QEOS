import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatPassRate } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { passRateWeeksQuery } from "../../lib/healthQueries";
import { passRateWeek } from "./passRateWeek";
import type { WidgetProps } from "./types";

/** This week's pass rate against last week's, as the API computed them (today's card; one branch when set, else every
 *  branch). */
export default function PassRateWeekWidget({ projectId, settings, heading }: WidgetProps) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const weeks = useQuery(passRateWeeksQuery(projectId, tz, settings.branch));
  const buckets = weeks.data?.days ?? [];
  const thisWeek = buckets[buckets.length - 1];
  const lastWeek = buckets.length > 1 ? buckets[buckets.length - 2] : undefined;
  return (
    <>
      {heading}
      {weeks.isPending && <SkeletonStat label="Loading pass rate…" />}
      {weeks.error != null && <ErrorBanner error={weeks.error} onRetry={() => weeks.refetch()} />}
      {thisWeek && (
        <>
          <div className="stat-big">{formatPassRate(thisWeek.pass_rate)}</div>
          <p className="muted">
            {thisWeek.runs} {thisWeek.runs === 1 ? "run" : "runs"} this week
            {" · "}
            {lastWeek && lastWeek.pass_rate !== null
              ? `${formatPassRate(lastWeek.pass_rate)} the week before`
              : "no runs the week before"}
          </p>
        </>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={passRateWeek.link(projectId, settings)}>Trends <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
