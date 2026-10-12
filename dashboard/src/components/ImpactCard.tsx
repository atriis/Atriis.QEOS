import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatCount } from "../api/analytics";
import type { ImpactOutcome, RunImpact, SuggestedTest } from "../api/impact";
import { normally, runImpactQuery } from "../lib/impactQueries";
import { plural, testHistoryPath } from "../lib/words";
import ErrorBanner from "./ErrorBanner";
import { SkeletonStatus } from "./Skeleton";
import StatusPill from "./StatusPill";

/** Lines shown before "Show all" (plan Ruling 26). */
export const IMPACT_SHOWN = 15;

const LABELS: Record<Exclude<SuggestedTest["kind"], "statistical">, string> = {
  test_file_changed: "test file changed",
  no_history: "no history yet",
  failing_on_branch: "failing on this branch",
};

/** A statistical suggestion's evidence in words; an always-included test's label. The base rate is left out when the
 *  API has none (the test never newly failed otherwise). */
function Evidence({ test }: { test: SuggestedTest }) {
  if (test.kind !== "statistical") return <StatusPill tone="neutral" label={LABELS[test.kind]} />;
  const e = test.evidence;
  if (e === null) return null;
  const usual = normally(e.base_rate);
  return (
    <span className="muted impact-evidence">
      newly failed in {formatCount(e.new_failures)} of {formatCount(e.changed_runs)} runs that changed <code>{e.path_unit}</code>
      {usual !== null && <> <span className="impact-usual">({usual})</span></>}
    </span>
  );
}

/** "Suggested 12 tests · 3 newly failed · all 3 were suggested", or the missed ones by name (spec §2.1). The pills say
 *  it in a word and an icon as well as a colour (Never Alone). */
function Outcome({ projectId, suggested, outcome }: { projectId: number; suggested: number; outcome: ImpactOutcome | null }) {
  const lead = `Suggested ${plural(suggested, "test", "tests")}`;
  if (outcome === null) return <p className="muted impact-outcome">{`${lead} · outcome not recorded yet`}</p>;
  const failed = outcome.caught.length + outcome.missed.length;
  if (failed === 0) return <p className="impact-outcome">{`${lead} · no new failures`}</p>;
  const newly = `${formatCount(failed)} newly failed`;
  if (outcome.missed.length === 0) {
    const tail = failed === 1 ? "it was suggested" : `all ${formatCount(failed)} were suggested`;
    return (
      <p className="impact-outcome">
        <StatusPill tone="passed" label="All caught" /> <span>{`${lead} · ${newly} · ${tail}`}</span>
      </p>
    );
  }
  return (
    <div className="impact-outcome">
      <p>
        <StatusPill tone="failed" label="Missed" />{" "}
        <span>{`${lead} · ${newly} · ${formatCount(outcome.missed.length)} not suggested:`}</span>
      </p>
      <ul className="impact-list">
        {outcome.missed.map((t) => <li key={t.test_key}><Link to={testHistoryPath(projectId, t.test_key)}>{t.name}</Link></li>)}
      </ul>
    </div>
  );
}

function Body({ projectId, data }: { projectId: number; data: RunImpact }) {
  const [all, setAll] = useState(false);
  if (data.state === "no_change_data") return <p className="muted">No change data for this run</p>;
  const s = data.suggestion;
  if (data.state === "not_scored" || s === null) {
    return <p className="muted">No suggestion was stored for this run: it was uploaded before test impact analysis, or scoring failed.</p>;
  }
  const statistical = s.tests.filter((t) => t.kind === "statistical").length;
  const shown = all ? s.tests : s.tests.slice(0, IMPACT_SHOWN);
  return (
    <>
      {data.replayed && <p className="muted">Replayed: scored later from the runs before this one, not at upload.</p>}
      {s.state === "not_enough_history" && (
        <p className="muted impact-outcome">
          {`Not enough history yet: ${plural(s.history_runs, "run", "runs")} with changed files, needs ${formatCount(s.needed_runs)}`}
        </p>
      )}
      <Outcome projectId={projectId} suggested={s.tests.length} outcome={data.outcome} />
      {s.tests.length === 0 ? (
        <p className="muted">{s.state === "not_enough_history" ? "Nothing to suggest yet." : "No tests are likely affected by this change"}</p>
      ) : (
        <ul className="impact-list">
          {shown.map((t) => (
            <li key={t.test_key}><Link to={testHistoryPath(projectId, t.test_key)}>{t.name}</Link> <Evidence test={t} /></li>
          ))}
        </ul>
      )}
      {s.statistical_total > statistical && (
        <p className="muted impact-outcome">
          {`Showing the ${formatCount(statistical)} strongest of ${formatCount(s.statistical_total)} statistical suggestions`}
        </p>
      )}
      {s.tests.length > IMPACT_SHOWN && (
        <button type="button" className="ghost" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${formatCount(s.tests.length)}`}
        </button>
      )}
    </>
  );
}

/** "Likely affected tests" beside a run's Changes (spec 2026-10-12 §2.1): the suggestion stored at upload, each test's
 *  evidence or label, and the outcome once the run's results were compared. Loads and fails on its own. */
export default function ImpactCard({ projectId, runId }: { projectId: number; runId: number }) {
  const titleId = useId();
  const query = useQuery(runImpactQuery(projectId, runId));
  return (
    <section className="card impact-card" aria-labelledby={titleId}>
      <div className="impact-head">
        <h2 id={titleId}>Likely affected tests</h2>
        {query.data?.replayed && <StatusPill tone="neutral" label="Replayed" />}
      </div>
      {query.isPending && (
        <SkeletonStatus label="Loading likely affected tests…">
          <span className="skeleton skeleton-block" style={{ height: 96 }} aria-hidden="true" />
        </SkeletonStatus>
      )}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => void query.refetch()} />}
      {query.data && <Body projectId={projectId} data={query.data} />}
    </section>
  );
}
