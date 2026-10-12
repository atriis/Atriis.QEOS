import { Link } from "react-router-dom";
import { formatCount, formatPassRate } from "../../../api/analytics";
import type { AccuracyDays, AccuracyPart, ImpactAccuracy } from "../../../api/impact";
import StatusPill from "../../../components/StatusPill";
import { caughtText, useImpactAccuracy } from "../../../lib/impactQueries";
import { dateFormat, plural, testHistoryPath } from "../../../lib/words";
import ReportSection from "../ReportSection";

/** Suggested tests per run: one decimal at most, the locale's separators. */
const perRun = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

function part(p: AccuracyPart): string {
  const runs = plural(p.runs, "run", "runs");
  return p.caught + p.missed === 0 ? `${runs}, no new failures` : `caught ${caughtText(p.caught, p.missed)} in ${runs}`;
}

interface Props {
  projectId: number;
  days: AccuracyDays;
  /** False when the Report's period is not the last 7, 14 or 30 days, so `days` is the 30-day fallback (Ruling 21). */
  followsReport: boolean;
  onResetFilters: () => void;
}

/** Test impact (spec 2026-10-12 §2.3, §9; plan Ruling 21): how often the suggestions stored with runs contained their new
 *  failures, over the last 7, 14 or 30 days on every branch, beside how many tests they suggested per run (suggesting
 *  every test would catch everything), live and replayed apart, with the misses. */
export default function ImpactSection({ projectId, days, followsReport, onResetFilters }: Props) {
  const query = useImpactAccuracy(projectId, days);
  const span = followsReport
    ? `Last ${days} days, every branch`
    : `Last ${days} days, every branch (the Report's period is not the last 7, 14 or 30 days)`;
  return (
    <ReportSection
      id="report-impact" title="Test impact" query={query} height={160} onResetFilters={onResetFilters}
      note={`${span}: how often the likely affected tests stored with each run contained its new failures. The other filters do not apply.`}
      isEmpty={(a: ImpactAccuracy) => a.live.runs + a.replayed.runs === 0}
      emptyText={`No run with a stored suggestion in the last ${days} days`}
    >
      {(a: ImpactAccuracy) => (
        <>
          <div className="impact-figures">
            <div>
              <div className="stat-big">{formatPassRate(a.rate)}</div>
              <p>{a.rate === null
                ? `No new failures in ${plural(a.live.runs + a.replayed.runs, "run", "runs")} with a stored suggestion`
                : `Suggestions caught ${caughtText(a.caught, a.missed)}`}</p>
            </div>
            <div>
              <div className="stat-big">{a.avg_suggested === null ? "—" : perRun.format(a.avg_suggested)}</div>
              <p>tests suggested per run, on average</p>
            </div>
          </div>
          {a.includes_replayed && (
            <dl className="impact-parts">
              <div><dt>Live</dt><dd>{part(a.live)}</dd></div>
              <div><dt>Replayed</dt><dd>{part(a.replayed)}</dd></div>
            </dl>
          )}
          {a.misses.length > 0 && (
            <table className="data">
              <caption className="sr-only">New failures the suggestions missed</caption>
              <thead>
                <tr>
                  <th scope="col">Missed test</th><th scope="col">Run</th><th scope="col">Branch</th>
                  <th scope="col" className="num">Started</th><th scope="col">Suggestion</th>
                </tr>
              </thead>
              <tbody>
                {a.misses.map((m) => (
                  <tr key={`${m.run_id}-${m.test_key}`}>
                    <td><Link to={testHistoryPath(projectId, m.test_key, m.branch)}>{m.name}</Link></td>
                    <td><Link to={`/projects/${projectId}/runs/${m.run_id}`}>{`#${m.run_id}`}</Link></td>
                    <td>{m.branch ?? "no branch"}</td>
                    <td className="num">{dateFormat.format(new Date(m.started_at))}</td>
                    <td>{m.replayed ? <StatusPill tone="neutral" label="Replayed" /> : "Live"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {a.misses_total > a.misses.length && (
            <p className="muted report-note">{`And ${formatCount(a.misses_total - a.misses.length)} more.`}</p>
          )}
        </>
      )}
    </ReportSection>
  );
}
