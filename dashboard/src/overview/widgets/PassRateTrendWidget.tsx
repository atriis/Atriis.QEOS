import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatPassRate } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import PassRateChart from "../../components/PassRateChart";
import { SkeletonStat } from "../../components/Skeleton";
import { trendsViewQuery } from "../../lib/healthQueries";
import EmptyBranch from "../EmptyBranch";
import { TREND_DAYS, passRateTrend } from "./passRateTrend";
import type { WidgetProps } from "./types";

/** The pass rate per bucket, the Trends view's chart under its own query key (one branch when set, else every branch). */
export default function PassRateTrendWidget({ projectId, settings, size, heading, titleId, onOpenSettings }: WidgetProps) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const bucket = settings.granularity ?? "week";
  const days = TREND_DAYS[bucket];
  const query = useQuery(trendsViewQuery(projectId, tz, days, bucket, settings.branch ?? ""));
  const buckets = query.data?.days ?? [];
  const noRuns = query.data !== undefined && buckets.every((d) => d.runs === 0);
  const last = buckets.filter((d) => d.pass_rate !== null).at(-1);
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStat label="Loading pass-rate trend…" />}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {noRuns && (settings.branch === undefined
        ? <p className="muted">No runs in the last {days} days.</p>
        : <EmptyBranch branch={settings.branch} days={days} onOpenSettings={onOpenSettings} titleId={titleId} />)}
      {query.data && !noRuns && (
        <>
          {/* A normal card is narrow: fewer ticks and a slimmer axis */}
          <PassRateChart buckets={buckets} bucket={bucket} height={size === "wide" ? 220 : 160} narrow={size === "normal"} labelledBy={titleId} />
          {last && <p className="muted">Latest {bucket}: {formatPassRate(last.pass_rate)}</p>}
        </>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={passRateTrend.link(projectId, settings)}>Trends <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
