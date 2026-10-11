import { Link, useParams } from "react-router-dom";
import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LIVE_REFRESH_MS } from "../lib/live";
import { ArrowRight, Clock, GitBranch, GitCommitHorizontal, Server } from "lucide-react";
import { formatDuration, formatPassRate } from "../api/analytics";
import { getFailureGroups, listRuns, Run } from "../api/runs";
import { isNewCause } from "../components/FailureGroups";
import RunStatusBadge from "../components/RunStatusBadge";
import ErrorBanner from "../components/ErrorBanner";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import StatusDot from "../components/StatusDot";
import PageHeader from "../components/PageHeader";
import { flakyHealthQuery, passRateWeeksQuery } from "../lib/healthQueries";
import { ago } from "../overview/format";

const MAX_CAUSES = 5;

/** "What is broken now" in one screen: the latest run's verdict and failures,
 *  then the week's pass rate and the flaky count, each one click from depth. */
export default function OverviewPage() {
  return (
    <>
      <PageHeader title="Overview" />
      <OverviewBody />
    </>
  );
}

function OverviewBody() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ["runs", id, "latest"],
    queryFn: () => listRuns(id, { limit: 1, offset: 0 }),
    refetchInterval: LIVE_REFRESH_MS,
  });
  const latest: Run | undefined = runs.data?.[0];
  // A new upload moves the week's pass rate and the flaky count too
  const shownRun = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (shownRun.current !== undefined && latest?.id !== shownRun.current) {
      queryClient.invalidateQueries({ queryKey: ["trends", id] });
      queryClient.invalidateQueries({ queryKey: ["flaky", id] });
    }
    shownRun.current = latest?.id;
  }, [latest?.id, id, queryClient]);
  const causes = useQuery({
    queryKey: ["failure-groups", latest?.id],
    queryFn: () => getFailureGroups(latest!.id),
    enabled: latest !== undefined && latest.failed + latest.errored > 0,
  });
  // Shared with the Cases KPI tiles
  const weeks = useQuery({
    ...passRateWeeksQuery(id, tz),
    enabled: latest !== undefined,
  });
  const flaky = useQuery({
    ...flakyHealthQuery(id),
    enabled: latest !== undefined,
  });

  if (runs.error != null) return <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />;
  if (runs.isPending) {
    return (
      <SkeletonStatus label="Loading overview…" className="overview-grid">
        <SkeletonCard className="wide" height={96} />
        <SkeletonCard height={120} />
        <SkeletonCard height={120} />
        <SkeletonCard height={120} />
      </SkeletonStatus>
    );
  }

  if (!latest) {
    return (
      <div className="card">
        <h2>No runs yet</h2>
        <p className="muted">
          Results appear here after the first upload from CI. Create an API key, paste the CI
          snippet into your pipeline, and the next build reports its tests.
        </p>
        <Link className="link-arrow" to={`/projects/${id}/settings`}>Set up an API key and CI <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    );
  }

  const broken = latest.failed + latest.errored;
  // Failures of quarantined tests are shown but do not decide the verdict
  const held = causes.data?.quarantined ?? 0;
  const blocking = causes.data?.blocking ?? broken;
  const groups = causes.data?.groups ?? [];
  const buckets = weeks.data?.days ?? [];
  const thisWeek = buckets[buckets.length - 1];
  const lastWeek = buckets.length > 1 ? buckets[buckets.length - 2] : undefined;
  // The shared query includes quarantined tests; this card counts the others, as the Flaky view does by default
  const unmuted = flaky.data?.filter((r) => !r.muted) ?? [];
  const confirmed = unmuted.filter((r) => r.reason === "same_commit").length;
  const suspected = unmuted.filter((r) => r.reason === "flips").length;

  return (
    <div className="overview-grid">
      <section className="card wide" aria-labelledby="latest-run">
        <div className="card-head">
          <h2 id="latest-run">Latest run</h2>
          <RunStatusBadge verdict={blocking > 0 ? "failed" : "passed"} note={blocking === 0 && held > 0 ? `${held} quarantined` : undefined} />
        </div>
        {latest.commit_message && <p>{latest.commit_message}</p>}
        <div className="meta">
          {latest.branch && <span><GitBranch size={14} aria-hidden="true" /> {latest.branch}</span>}
          {latest.commit_sha && <span><GitCommitHorizontal size={14} aria-hidden="true" /> <code>{latest.commit_sha.slice(0, 7)}</code></span>}
          {latest.environment && <span><Server size={14} aria-hidden="true" /> {latest.environment}</span>}
          <span><Clock size={14} aria-hidden="true" /> {ago(latest.started_at)} · {formatDuration(latest.duration_ms)}</span>
        </div>
        <div className="meta">
          <span><StatusDot status="passed" label={`${latest.passed} passed`} /></span>
          <span><StatusDot status="failed" label={`${latest.failed} failed`} /></span>
          <span><StatusDot status="errored" label={`${latest.errored} errored`} /></span>
          <span><StatusDot status="skipped" label={`${latest.skipped} skipped`} /></span>
        </div>
        <div className="card-foot">
          <Link className="link-arrow" to={`/projects/${id}/runs/${latest.id}`}>Open run #{latest.id} <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </section>

      <section className="card" aria-labelledby="failing">
        <h2 id="failing">Failing in this run</h2>
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
              {groups.slice(0, MAX_CAUSES).map((g) => {
                const first = g.tests[0];
                return (
                  <li key={g.signature}>
                        <span className="cause-title">
                      {isNewCause(g.history) && <span className="badge badge-new">New</span>}
                      {g.headline ? <span className="msg">{g.headline}</span> : <span className="where">No error message</span>}
                    </span>
                    <span>
                      <Link to={`/projects/${id}/tests/${encodeURIComponent(first.test_key)}`}>{first.name}</Link>
                      {g.count > 1 && <span className="where"> and {g.count - 1} more</span>}
                      {(g.quarantined ?? 0) > 0 && <span className="where"> · {g.quarantined === g.count ? "in quarantine" : `${g.quarantined} in quarantine`}</span>}
                    </span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        {broken > 0 && (groups.length > MAX_CAUSES || groups.some((g) => g.count > 1)) && (
          <div className="card-foot">
            <Link className="link-arrow" to={`/projects/${id}/runs/${latest.id}`}>All {broken} failures by cause <ArrowRight size={14} aria-hidden="true" /></Link>
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="pass-rate">
        <h2 id="pass-rate">Pass rate this week</h2>
        {weeks.isPending && <SkeletonStatus label="Loading pass rate…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
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
          <Link className="link-arrow" to={`/projects/${id}/trends`}>Trends <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </section>

      <section className="card" aria-labelledby="flaky-count">
        <h2 id="flaky-count">Flaky tests, last 14 days</h2>
        {flaky.isPending && <SkeletonStatus label="Loading flaky tests…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
        {flaky.error != null && <ErrorBanner error={flaky.error} onRetry={() => flaky.refetch()} />}
        {flaky.data && (
          <>
            <div className="stat-big">{confirmed + suspected}</div>
            <p className="muted">{confirmed} confirmed · {suspected} suspected</p>
          </>
        )}
        <div className="card-foot">
          <Link className="link-arrow" to={`/projects/${id}/flaky`}>Flaky tests <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </section>
    </div>
  );
}
