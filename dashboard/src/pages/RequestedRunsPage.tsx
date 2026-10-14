import NarrowMeta from "../components/NarrowMeta";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { listRunRequests } from "../api/runRequests";
import { listRuns } from "../api/runs";
import ErrorBanner from "../components/ErrorBanner";
import StatusPill, { type PillTone } from "../components/StatusPill";
import { MATCH_SLACK_MS, describeRun, matchRun, type RunTone } from "../lib/runStatus";
import { requestTiming } from "../lib/durationEstimate";
import { RUN_POLL_MS } from "../lib/useRunGate";
import { useUserNames } from "../lib/useUserNames";
import { pageOffset, withOffset } from "../lib/useUrlState";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const PAGE = 50;
const PILL_TONE: Record<RunTone, PillTone> = {
  queued: "queued", running: "running", passed: "passed", failed: "failed", cancelled: "cancelled", skipped: "skipped", error: "errored",
};

/** The status word goes in the pill; what follows it ("1 test · started by …", the error) sits beside it */
function splitStatus(text: string): [string, string] {
  const m = /^(.*?)(?: · |: )(.*)$/.exec(text);
  return m ? [m[1], m[2]] : [text, ""];
}

/** Runs → Requested runs: every Play, who pressed it, how it ended, and where its results are. */
export default function RequestedRunsPage() {
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const { projectId } = useParams();
  const id = Number(projectId);
  const [params, setParams] = useSearchParams();
  const offset = pageOffset(params, PAGE);
  const setOffset = (to: number) => setParams((prev) => withOffset(prev, to));
  const nameOf = useUserNames(id);
  const list = useQuery({
    queryKey: ["run-requests", id, "page", offset],
    queryFn: () => listRunRequests(id, { limit: PAGE, offset }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.refreshing) ? RUN_POLL_MS : false),
  });
  const items = list.data?.items ?? [];
  // Read at each render: the list re-renders on every poll while a request is active, so "≈ 4 min left" keeps up
  const now = Date.now();
  const oldest = items.length > 0 ? Math.min(...items.map((r) => Date.parse(r.requested_at))) : null;
  const runs = useQuery({
    queryKey: ["run-requests", id, "page-results", offset, oldest],
    queryFn: () => listRuns(id, { limit: 100, offset: 0, since: new Date((oldest ?? 0) - MATCH_SLACK_MS).toISOString(), ci_provider: "github_actions" }),
    enabled: oldest !== null && items.some((r) => r.github_run_url),
  });

  return (
    <section>
      <PageHeader title="Requested runs" tabs={[{ label: "Runs", to: ".." }, { label: "Requested runs" }]} />
      {list.error != null && <ErrorBanner error={list.error} onRetry={() => list.refetch()} />}
      {list.isPending && <p className="muted">Loading requested runs…</p>}
      {list.data && list.data.total === 0 && <p className="muted">No runs requested from QEOS yet.</p>}
      {items.length > 0 && (
        <div ref={card.ref} className={tableCardClass(card.wide)} tabIndex={0} role="region" aria-label="Requested runs">
          <table className="data">
            <thead>
              <tr>
                <th>Date</th><th>Requested by</th><th className="num">Cases</th><th>Status</th>
                <th className="hide-narrow">Stopped by</th><th>Links</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const result = matchRun(runs.data ?? [], r.github_run_url);
                const described = describeRun(r, nameOf);
                const [word, rest] = splitStatus(described.text);
                const timing = requestTiming(r, now, result);
                return (
                  <tr key={r.id}>
                    <td>
                      {new Date(r.requested_at).toLocaleString()}
                      <NarrowMeta items={[{ label: "Stopped by", value: r.stopped_by != null ? nameOf(r.stopped_by) : null }]} />
                    </td>
                    <td>{nameOf(r.requested_by)}</td>
                    <td className="num">{r.case_count}</td>
                    <td>
                      <StatusPill tone={PILL_TONE[described.tone]} label={word} />
                      {rest && <> <span className="pill-detail">{rest}</span></>}
                      {described.detail && <div className="muted run-panel-detail">{described.detail}</div>}
                      {timing && <div className="muted run-estimate-detail">{timing}</div>}
                    </td>
                    <td className="hide-narrow">{r.stopped_by != null ? nameOf(r.stopped_by) : "—"}</td>
                    <td className="row-actions">
                      {r.github_run_url && (
                        <a href={r.github_run_url} target="_blank" rel="noopener noreferrer" className="link-arrow">
                          GitHub <ExternalLink size={13} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span>
                        </a>
                      )}
                      {result && <Link to={`/projects/${id}/runs/${result.id}`}>{`Run #${result.id}`}</Link>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="pager">
            <span className="muted">{offset + 1}–{offset + items.length} of {list.data?.total}</span>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <button disabled={offset + PAGE >= (list.data?.total ?? 0)} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>
        </div>
      )}
    </section>
  );
}
