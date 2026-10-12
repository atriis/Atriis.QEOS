import { formatPassRate } from "../../api/analytics";
import type { AccuracyDays } from "../../api/impact";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { caughtText, useImpactAccuracy } from "../../lib/impactQueries";
import { plural } from "../../lib/words";
import WidgetEmpty from "../WidgetEmpty";
import ReportFoot from "./ReportFoot";
import { impactAccuracy } from "./impactAccuracy";
import type { WidgetProps } from "./types";

/** Suggested tests per run: one decimal at most, the locale's separators. */
const perRun = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

/** The Report's Test impact figure (spec 2026-10-12 §2.3, §9) under the same query: the share of new failures the
 *  stored suggestions caught over the period, on every branch, beside how many tests they suggested per run, with
 *  replayed runs counted and said. */
export default function ImpactAccuracyWidget({ projectId, settings, heading, titleId, onOpenSettings }: WidgetProps) {
  const days = (settings.period ?? 30) as AccuracyDays;
  const accuracy = useImpactAccuracy(projectId, days);
  const a = accuracy.data;
  const runs = a ? a.live.runs + a.replayed.runs : 0;
  return (
    <>
      {heading}
      {accuracy.isPending && <SkeletonStat label="Loading impact accuracy…" />}
      {accuracy.error != null && <ErrorBanner error={accuracy.error} onRetry={() => void accuracy.refetch()} />}
      {a && runs === 0 && (
        <WidgetEmpty onOpenSettings={onOpenSettings} titleId={titleId}>
          {`No run with a stored suggestion in the last ${days} days`}
        </WidgetEmpty>
      )}
      {a && runs > 0 && (
        <>
          <div className="stat-big">{formatPassRate(a.rate)}</div>
          <p className="muted">{a.rate === null ? `No new failures in ${plural(runs, "run", "runs")}` : `Caught ${caughtText(a.caught, a.missed)}`}</p>
          {a.avg_suggested !== null && <p className="muted">{`${perRun.format(a.avg_suggested)} tests suggested per run, on average`}</p>}
          {a.includes_replayed && <p className="muted">{`Includes ${plural(a.replayed.runs, "replayed run", "replayed runs")}`}</p>}
        </>
      )}
      <ReportFoot to={impactAccuracy.link(projectId, settings)} />
    </>
  );
}
