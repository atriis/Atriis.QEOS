import { useCallback, useEffect, useMemo, useRef } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RunStatusFilter, getRun, listRuns } from "../api/runs";
import { formatDuration } from "../api/analytics";
import ErrorBanner from "../components/ErrorBanner";
import FailureGroups from "../components/FailureGroups";
import FilterBar from "../components/FilterBar";
import ImpactCard from "../components/ImpactCard";
import Message from "../components/Message";
import StatusDot from "../components/StatusDot";
import { oneOf, useUrlState } from "../lib/useUrlState";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const DEFAULTS = { status: "" } as const;
const STATUSES = ["passed", "failed", "errored", "skipped"] as const;
// The API returns every result of the run (no limit/offset), so the table pages on the client.
const PAGE = 100;
/** Failing results lead: that is what a reader opens a run for. Order: failed, errored, anything else, skipped, passed.
 *  Stable, so each group keeps the API's order. */
const RANK: Record<string, number> = { failed: 0, errored: 1, skipped: 3, passed: 4 };
const OTHER_RANK = 2;

export default function RunDetailPage() {
  const { projectId, runId } = useParams();
  const id = Number(runId);
  const { values, offset, update, setOffset } = useUrlState(DEFAULTS, PAGE);
  const status: RunStatusFilter | "" = oneOf(values.status, STATUSES, "" as never);

  const query = useQuery({
    queryKey: ["run", id, status],
    queryFn: () => getRun(id, status || undefined),
    // Keep the page (and the focused select) mounted while a new filter loads, but never show another run's data
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[1] === id ? previous : undefined),
  });

  const run = query.data;
  const ordered = useMemo(
    () => [...(run?.results ?? [])].sort((a, b) => (RANK[a.status] ?? OTHER_RANK) - (RANK[b.status] ?? OTHER_RANK)),
    [run?.results],
  );
  // A link to a page past the end (a shorter run, an edited URL) shows the last page, not an empty one
  const start = Math.min(offset, Math.max(0, Math.floor((ordered.length - 1) / PAGE) * PAGE));
  const shown = ordered.slice(start, start + PAGE);
  // A new page starts at the top of the table: after Next the reader would otherwise be left at the bottom of the old one
  const tableRef = useRef<HTMLDivElement | null>(null);
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const setCard = card.ref;
  const cardRef = useCallback((node: HTMLDivElement | null) => {
    tableRef.current = node;
    setCard(node);
  }, [setCard]);
  const shownStart = useRef(start);
  useEffect(() => {
    if (shownStart.current !== start) tableRef.current?.scrollIntoView?.({ block: "start" });
    shownStart.current = start;
  }, [start]);
  // The run before this one on the same branch: the natural thing to compare with
  const previous = useQuery({
    queryKey: ["runs", Number(projectId), "before", id],
    queryFn: () =>
      listRuns(Number(projectId), { limit: 1, offset: 0, until: run!.started_at, ...(run!.branch ? { branch: run!.branch } : {}) }),
    enabled: run !== undefined,
  });
  const previousRun = previous.data?.[0];

  return (
    <section>
      <p>
        <Link className="link-arrow" to=".." relative="path"><ArrowLeft size={14} aria-hidden="true" /> All runs</Link>
      </p>
      <PageHeader title={`Run #${id}`} />

      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {query.isPending && <p className="muted">Loading run…</p>}

      {run && (
        <>
          <p className="muted">
            <span>{new Date(run.started_at).toLocaleString()}</span> ·{" "}
            <span>{run.branch ?? "no branch"}</span> ·{" "}
            <span>{run.commit_sha ? run.commit_sha.slice(0, 7) : "no commit"}</span> ·{" "}
            <span>{run.environment ?? "no environment"}</span> ·{" "}
            {run.ci_run_url ? (
              <a href={run.ci_run_url} target="_blank" rel="noreferrer">{run.ci_provider}</a>
            ) : (
              run.ci_provider
            )}
          </p>
          {run.components.length > 0 && (
            <p className="muted">
              Under test:{" "}
              {run.components.map((c, i) => (
                <span key={c.name}>
                  {i > 0 && " · "}
                  <code>{c.name}@{c.sha.slice(0, 12)}</code>
                </span>
              ))}
            </p>
          )}
          {(run.commit_author || run.commit_message || run.pr_number || run.base_branch) && (
            <p className="muted">
              {run.commit_author && <span>{run.commit_author}</span>}
              {run.commit_message && <span> · {run.commit_message}</span>}
              {run.pr_number && <span> · PR #{run.pr_number}</span>}
              {run.base_branch && <span> · into {run.base_branch}</span>}
            </p>
          )}
          {previousRun && (
            <p>
              <Link className="link-arrow" to={`compare/${previousRun.id}`}>
                Compare with previous run #{previousRun.id}
              </Link>
            </p>
          )}
          <div className="tiles">
            <div className="card">
              <div className="tile-value">{run.total}</div>
              <div className="tile-label">Results</div>
            </div>
            <div className="card">
              <div className="tile-value">{run.passed}</div>
              <div className="tile-label">Passed</div>
            </div>
            <div className="card">
              <div className="tile-value">{run.blocking ?? run.failed + run.errored}</div>
              <div className="tile-label">Failing</div>
              {(run.quarantined ?? 0) > 0 && (
                <div className="tile-note">{run.quarantined} in quarantine, not counted</div>
              )}
            </div>
            <div className="card">
              <div className="tile-value">{formatDuration(run.duration_ms)}</div>
              <div className="tile-label">Duration</div>
            </div>
          </div>

          {run.failed + run.errored > 0 && <FailureGroups runId={run.id} projectId={projectId} />}

          {/* The impact card is on every run, so a run without changed files says "No change data" (spec §2.1) */}
          <div className="run-change-cards">
            {run.change_base_ref !== null && (
              <div className="card">
                <h2>Changes</h2>
                <p className="muted">
                  {run.changed_files} file(s), +{run.additions ?? 0} −{run.deletions ?? 0} vs {run.change_base_ref}
                  {run.changes_truncated && <span> · list truncated at 1000 files</span>}
                </p>
                {run.changes.length > 0 && (
                  <table className="data">
                    <thead>
                      <tr>
                        <th>File</th><th>Status</th><th className="num">+</th><th className="num">−</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.changes.map((f) => (
                        <tr key={f.path}>
                          <td>{f.path}</td>
                          <td>{f.status}</td>
                          <td className="num">{f.additions ?? "—"}</td>
                          <td className="num">{f.deletions ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
            <ImpactCard projectId={Number(projectId)} runId={run.id} branch={run.branch} />
          </div>

          <FilterBar>
            <label>
              Status
              <select value={status} onChange={(e) => update({ status: e.target.value })}>
                <option value="">all</option>
                <option value="passed">passed</option>
                <option value="failed">failed</option>
                <option value="errored">errored</option>
                <option value="skipped">skipped</option>
              </select>
            </label>
          </FilterBar>
          <p role="status" className="muted">{query.isPlaceholderData && "Updating results…"}</p>

          {run.results.length === 0 ? (
            <p className="muted">No {status || ""} results in this run.</p>
          ) : (
            <div className={tableCardClass(card.wide)} ref={cardRef} tabIndex={0} role="region" aria-label="Test results">
              <table className="data">
                <thead>
                  <tr>
                    <th>Test</th><th>Status</th><th className="num">Duration</th><th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link to={`/projects/${projectId}/tests/${encodeURIComponent(r.test_key)}`}>
                          {r.name}
                        </Link>
                        <div className="muted">
                          {r.suite} / {r.class_name}
                          {r.owner && <span> · {r.owner}</span>}
                          {r.truncated && <span> · truncated</span>}
                          {r.redacted && <span> · redacted</span>}
                        </div>
                      </td>
                      <td>
                        <StatusDot status={r.status} />
                        {r.quarantined && <div className="muted">quarantined</div>}
                      </td>
                      <td className="num">{formatDuration(r.duration_ms)}</td>
                      <td><Message text={r.message} name={r.name} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {ordered.length > PAGE && (
                <div className="pager">
                  <span className="muted">{`Rows ${start + 1}–${start + shown.length} of ${ordered.length}`}</span>
                  <button disabled={start === 0} onClick={() => setOffset(Math.max(0, start - PAGE))}>Previous</button>
                  <button disabled={start + PAGE >= ordered.length} onClick={() => setOffset(start + PAGE)}>Next</button>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
