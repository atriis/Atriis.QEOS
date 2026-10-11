import { formatCount } from "../../../api/analytics";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Download } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type CauseGroup, type Report, testLabel } from "../../../api/report";
import { DataTableDisclosure, PATTERN } from "../../../components/ChartKit";
import StatusPill from "../../../components/StatusPill";
import { downloadCsv, toCsv } from "../../../lib/csv";
import ReportSection, { type SectionQuery } from "../ReportSection";
import type { Gate } from "../useReportRequest";

const TOP_IN_CHART = 10;
const day = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

const headlineOf = (g: { headline: string | null }) => g.headline ?? "(no message)";

export function causesCsv(r: Report): string {
  return toCsv(
    ["signature", "headline", "occurrences", "failed", "errored", "tests", "runs", "status", "previous_occurrences", "first_seen", "last_seen"],
    (r.failure_causes?.groups ?? []).map((g) => [g.signature, g.headline, g.occurrences, g.failed, g.errored, g.tests, g.runs, g.status,
      g.previous_occurrences, g.first_seen, g.last_seen]),
  );
}

/** A small line of the cause per bucket; the numbers are in its text equivalent, never only in the drawing. */
function Sparkline({ values, unit }: { values: number[]; unit: string }) {
  const max = Math.max(1, ...values);
  const width = 80;
  const height = 20;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(height - (v / max) * (height - 2) - 1).toFixed(1)}`).join(" ");
  return (
    <span className="sparkline">
      <svg width={width} height={height} aria-hidden="true" focusable="false">
        <polyline points={points} fill="none" stroke="var(--status-failed)" strokeWidth="1.5" />
      </svg>
      <span className="sr-only">per {unit}: {values.join(", ")}</span>
    </span>
  );
}

function StatusTag({ g }: { g: CauseGroup }) {
  return g.status === "new" ? <StatusPill tone="failed" label="New" /> : <StatusPill tone="neutral" label="Recurring" />;
}

interface Props {
  projectId: number;
  gate: Gate;
  query: SectionQuery;
  branch: string | null;
  onResetFilters: () => void;
}

/** Section 2 (spec: Section 2: Failure causes): the run view's signature groups over the period, new or recurring
 *  against the previous period. */
export default function FailureCausesSection({ projectId, gate, query, branch, onResetFilters }: Props) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (sig: string) => setOpen((o) => {
    const next = new Set(o);
    if (next.has(sig)) next.delete(sig);
    else next.add(sig);
    return next;
  });
  const history = (key: string) => `/projects/${projectId}/tests/${encodeURIComponent(key)}${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`;

  return (
    <ReportSection
      id="report-causes"
      title="Failure causes"
      gate={gate}
      query={query}
      height={360}
      onResetFilters={onResetFilters}
      actions={query.data?.failure_causes && query.data.scope.runs > 0 ? (
        <button type="button" onClick={() => downloadCsv(`report-${projectId}-${query.data?.period.from}-${query.data?.period.to}-causes.csv`, query.data ? causesCsv(query.data) : "")}>
          <Download size={15} aria-hidden="true" /> Causes CSV
        </button>
      ) : undefined}
    >
      {(r) => {
        const c = r.failure_causes;
        if (!c) return null;
        const resolved = c.resolved.length > 0 && (
          <>
            <h3 id="report-resolved">Resolved since the previous period</h3>
            <ul className="plain-list" aria-labelledby="report-resolved">
              {c.resolved.map((x) => (
                <li key={x.signature}>
                  <span className="wrap-anywhere">{headlineOf(x)}</span>
                  <span className="muted"> · {formatCount(x.previous_occurrences)} before, last seen {day.format(new Date(x.last_seen))}</span>
                </li>
              ))}
            </ul>
          </>
        );
        if (c.groups.length === 0) return <><p className="muted">No failures in this period.</p>{resolved}</>;
        const periodStart = Date.parse(r.period.start);
        const unit = r.bucket;
        const chart = c.groups.slice(0, TOP_IN_CHART).map((g) => ({
          label: `${g.status === "new" ? "New · " : ""}${truncate(headlineOf(g), 80)}`,
          signature: g.signature, occurrences: g.occurrences, status: g.status,
        }));
        const largest = c.groups[0];
        const caption = `${formatCount(c.failures)} failures from ${formatCount(c.groups_total)} causes; the largest is `
          + `${truncate(headlineOf(largest), 80)} with ${formatCount(largest.occurrences)}`
          + `${largest.status === "new" ? ", new in this period" : ""}.`;
        return (
          <>
            {r.scope.previous_runs === 0 && (
              <p className="muted report-note">No data in the previous period, so every cause is new.</p>
            )}
            <figure className="chart-figure" aria-labelledby="report-causes">
              <figcaption className="sr-only">{caption}</figcaption>
              <ResponsiveContainer width="100%" height={Math.max(160, chart.length * 32)}>
                <BarChart data={chart} layout="vertical" margin={{ left: 8, right: 48 }} accessibilityLayer>
                  <CartesianGrid stroke="var(--grid)" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} stroke="var(--text-muted)" tick={{ fill: "var(--text-secondary)", fontSize: 12 }} />
                  <YAxis type="category" dataKey="label" width={260} stroke="var(--text-muted)" tick={{ fill: "var(--text-secondary)", fontSize: 12 }} />
                  <Tooltip contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 }} />
                  <Bar dataKey="occurrences" name="Occurrences" stroke="var(--surface-1)">
                    {chart.map((d) => (
                      <Cell key={d.signature} fill={d.status === "new" ? `url(#${PATTERN.failed})` : "var(--status-failed)"} />
                    ))}
                    <LabelList dataKey="occurrences" position="right" fill="var(--text-secondary)" fontSize={12} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </figure>
            <p className="muted report-note">New causes are striped and tagged "New"; recurring ones are solid.</p>
            <DataTableDisclosure name="failure causes chart">
              <table className="data">
                <thead><tr><th scope="col">Cause</th><th scope="col" className="num">Occurrences</th><th scope="col">Status</th></tr></thead>
                <tbody>{c.groups.slice(0, TOP_IN_CHART).map((g) => (
                  <tr key={g.signature}><td className="wrap-anywhere">{headlineOf(g)}</td><td className="num">{formatCount(g.occurrences)}</td><td>{g.status === "new" ? "New" : "Recurring"}</td></tr>
                ))}</tbody>
              </table>
            </DataTableDisclosure>

            <table className="data">
              <caption className="sr-only">Failure causes</caption>
              <thead><tr>
                <th scope="col">Cause</th><th scope="col" className="num">Occurrences</th>
                <th scope="col" className="num hide-narrow">Tests</th><th scope="col" className="num hide-narrow">Runs</th>
                <th scope="col">Status</th><th scope="col" className="hide-narrow">First seen</th><th scope="col">Last seen</th>
                <th scope="col" className="hide-narrow">Trend</th>
              </tr></thead>
              <tbody>
                {c.groups.map((g) => {
                  const expanded = open.has(g.signature);
                  const before = Date.parse(g.first_seen) < periodStart;
                  return (
                    <Fragment key={g.signature}>
                      <tr>
                        <td className="wrap-anywhere">
                          <button type="button" className="row-toggle" aria-expanded={expanded}
                            aria-label={`Show tests for ${truncate(headlineOf(g), 80)}`} onClick={() => toggle(g.signature)}>
                            <ChevronRight size={14} aria-hidden="true" className="chevron" />
                          </button>
                          {headlineOf(g)}
                          {g.quarantined > 0 && <span className="muted"> · {formatCount(g.quarantined)} quarantined</span>}
                        </td>
                        <td className="num">{formatCount(g.occurrences)}</td>
                        <td className="num hide-narrow">{formatCount(g.tests)}</td>
                        <td className="num hide-narrow">{formatCount(g.runs)}</td>
                        <td><StatusTag g={g} /></td>
                        <td className="hide-narrow">{before ? `seen since at least ${day.format(new Date(r.previous_period.start))}` : day.format(new Date(g.first_seen))}</td>
                        <td><Link to={`/projects/${projectId}/runs/${g.last_seen_run_id}`}>{day.format(new Date(g.last_seen))} (run #{g.last_seen_run_id})</Link></td>
                        <td className="hide-narrow"><Sparkline values={g.buckets} unit={unit} /></td>
                      </tr>
                      {expanded && (
                        <tr className="row-detail">
                          <td colSpan={8}>
                            <ul className="plain-list">
                              {g.top_tests.map((t) => (
                                <li key={t.test_key}>
                                  <Link to={history(t.test_key)}>{testLabel(t)}</Link>
                                  <span className="muted"> · {formatCount(t.occurrences)} {t.occurrences === 1 ? "time" : "times"}</span>
                                </li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {c.other.groups > 0 && (
              <p className="muted report-note">And {formatCount(c.other.groups)} more causes with {formatCount(c.other.occurrences)} failures.</p>
            )}
            {resolved}
          </>
        );
      }}
    </ReportSection>
  );
}
