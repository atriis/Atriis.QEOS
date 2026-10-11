import { formatCount } from "../../../api/analytics";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type RegressionItem, type Report, testLabel } from "../../../api/report";
import { DataTableDisclosure, type LegendSeries, SeriesLegend } from "../../../components/ChartKit";
import { formatPointLabel, formatTick } from "../../../lib/chartFormat";
import { downloadCsv, toCsv } from "../../../lib/csv";
import DeltaTile from "../DeltaTile";
import ReportSection, { type SectionQuery } from "../ReportSection";
import type { Gate } from "../useReportRequest";

const when = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const axisTick = { fill: "var(--text-secondary)", fontSize: 12 } as const;
const LEGEND: LegendSeries[] = [
  { key: "flaky", label: "Flaky tests", paint: "var(--series-1)" },
  { key: "share", label: "Share of tests executed", paint: "var(--series-2)", line: { dash: "5 4" } },
];

/** A time to fix as people say it: minutes, hours to one decimal under a day, then whole days. */
export function formatSpan(ms: number | null): string {
  if (ms === null) return "—";
  const hours = ms / 3_600_000;
  if (hours < 1) return `${Math.round(ms / 60_000)} min`;
  if (hours < 24) return `${Math.round(hours * 10) / 10} h`;
  const days = Math.round(hours / 24);
  return `${days} ${days === 1 ? "day" : "days"}`;
}

const id = (t: RegressionItem) => [t.suite, t.class_name, t.name, t.test_key, t.branch];

export function newlyCsv(r: Report): string {
  return toCsv(["suite", "class_name", "name", "test_key", "branch", "failing_since", "last_passed_at", "failures", "headline"],
    (r.regressions?.newly_failing.items ?? []).map((t) => [...id(t), t.failing_since, t.last_passed_at, t.failures, t.headline]));
}
export function fixedCsv(r: Report): string {
  return toCsv(["suite", "class_name", "name", "test_key", "branch", "fixed_at", "failing_since", "failing_since_bounded", "time_to_fix_ms"],
    (r.regressions?.fixed.items ?? []).map((t) => [...id(t), t.fixed_at, t.failing_since, String(t.failing_since_bounded), t.time_to_fix_ms]));
}
export function longestCsv(r: Report): string {
  return toCsv(["suite", "class_name", "name", "test_key", "branch", "failing_since", "failing_since_bounded", "consecutive_failures", "headline"],
    (r.regressions?.longest_failing.items ?? []).map((t) => [...id(t), t.failing_since, String(t.failing_since_bounded), t.consecutive_failures, t.headline]));
}

interface Props {
  projectId: number;
  gate: Gate;
  query: SectionQuery;
  branch: string | null;
  onResetFilters: () => void;
}

/** Section 4 (spec: Section 4: Regressions and stability). Outcomes are compared per (test, branch), so the help text
 *  recommends a branch filter; it is on the default branch unless the reader picks another. */
export default function RegressionsSection({ projectId, gate, query, branch, onResetFilters }: Props) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) => setHidden((h) => {
    const next = new Set(h);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const history = (t: RegressionItem) =>
    `/projects/${projectId}/tests/${encodeURIComponent(t.test_key)}${t.branch ? `?branch=${encodeURIComponent(t.branch)}` : ""}`;
  const run = (runId: number, label: ReactNode) => <Link to={`/projects/${projectId}/runs/${runId}`}>{label}</Link>;
  const since = (iso: string, bounded: boolean) => `${bounded ? "at least since " : ""}${when.format(new Date(iso))}`;
  const more = (total: number, shown: number) => total > shown && <p className="muted report-note">And {formatCount(total - shown)} more.</p>;
  const csv = (r: Report, part: string, make: (r: Report) => string) => (
    <button type="button" onClick={() => downloadCsv(`report-${projectId}-${r.period.from}-${r.period.to}-${part}.csv`, make(r))}>
      <Download size={15} aria-hidden="true" /> {part.replace("-", " ")} CSV
    </button>
  );

  return (
    <ReportSection
      id="report-regressions"
      title="Regressions and stability"
      gate={gate}
      query={query}
      height={420}
      onResetFilters={onResetFilters}
      note={<>Outcomes are compared per test and branch{branch ? ` (on ${branch})` : "; pick a branch for one story per test"}.</>}
      actions={query.data?.regressions && query.data.scope.runs > 0 ? (
        <>{csv(query.data, "newly-failing", newlyCsv)}{csv(query.data, "fixed", fixedCsv)}{csv(query.data, "longest-failing", longestCsv)}</>
      ) : undefined}
    >
      {(r) => {
        const g = r.regressions;
        if (!g) return null;
        const unit = r.bucket;
        const ttf = g.time_to_fix;
        const median = `${formatSpan(ttf.median_ms)}${ttf.bounded > 0 ? ` (${ttf.bounded} at least)` : ""}`;
        const rows = g.flakiness.map((b) => ({
          date: b.date, flaky: b.flaky_tests,
          share: b.tests_executed > 0 ? Math.round((b.flaky_tests / b.tests_executed) * 1000) / 10 : null,
        }));
        const flaky = g.flakiness.reduce((n, b) => n + b.flaky_tests, 0);
        const busiest = [...g.flakiness].sort((a, b) => b.flaky_tests - a.flaky_tests)[0];
        const caption = busiest && busiest.flaky_tests > 0
          ? `${formatCount(flaky)} flaky test-${unit}s; most on ${formatPointLabel(busiest.date, unit)}: ${formatCount(busiest.flaky_tests)} flaky tests of ${formatCount(busiest.tests_executed)}.`
          : "No flips in this period.";
        return (
          <>
            <ul className="kpi-tiles" aria-label="Regression figures">
              <li><DeltaTile title="Newly failing" value={formatCount(g.newly_failing.total)} delta={null} noPrevious={false} /></li>
              <li><DeltaTile title="Fixed" value={formatCount(g.fixed.total)} delta={null} noPrevious={false} /></li>
              <li><DeltaTile title="Still failing" value={formatCount(g.longest_failing.total)} delta={null} noPrevious={false} /></li>
              <li><DeltaTile title="Median time to fix" value={median} delta={null} noPrevious={false} /></li>
            </ul>

            <h3 id="report-instability">Instability (flips) per {unit}</h3>
            <p className="muted report-note">
              A flip is a pass/fail change between a test's consecutive outcomes on one branch. This differs from the Flaky page's
              same-commit rule, which stays the reference for confirmed flaky tests.
            </p>
            <SeriesLegend series={LEGEND} hidden={hidden} onToggle={toggle} label="Show or hide a series" />
            <figure className="chart-figure" aria-labelledby="report-instability">
              <figcaption className="sr-only">{caption}</figcaption>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={rows} accessibilityLayer>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" stroke="var(--text-muted)" tick={axisTick} tickLine={false} tickFormatter={(d: string) => formatTick(d, unit)} minTickGap={16} />
                  <YAxis yAxisId="count" allowDecimals={false} stroke="var(--text-muted)" tick={axisTick} tickLine={false} width={40} />
                  <YAxis yAxisId="share" orientation="right" domain={[0, "auto"]} tickFormatter={(v: number) => `${v}%`} stroke="var(--text-muted)" tick={axisTick} tickLine={false} width={44} />
                  <Tooltip contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 }} labelFormatter={(d) => formatPointLabel(String(d), unit)} />
                  <Bar yAxisId="count" dataKey="flaky" name="Flaky tests" fill="var(--series-1)" hide={hidden.has("flaky")} radius={[4, 4, 0, 0]} />
                  <Line yAxisId="share" dataKey="share" name="Share of tests executed (%)" stroke="var(--series-2)" strokeWidth={2} strokeDasharray="5 4"
                    hide={hidden.has("share")} dot={{ r: 2.5, fill: "var(--series-2)", stroke: "var(--surface-1)" }} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </figure>
            <DataTableDisclosure name={`instability per ${unit}`}>
              <table className="data">
                <thead><tr><th scope="col">{unit === "day" ? "Date" : "Week of"}</th><th scope="col" className="num">Tests executed</th>
                  <th scope="col" className="num">Flaky tests</th><th scope="col" className="num">Flips</th></tr></thead>
                <tbody>{g.flakiness.map((b) => (
                  <tr key={b.date}><td>{formatPointLabel(b.date, unit)}</td><td className="num">{formatCount(b.tests_executed)}</td>
                    <td className="num">{formatCount(b.flaky_tests)}</td><td className="num">{formatCount(b.flips)}</td></tr>
                ))}</tbody>
              </table>
            </DataTableDisclosure>

            <h3>Newly failing</h3>
            {g.newly_failing.items.length === 0 ? <p className="muted">None in this period.</p> : (
            <table className="data">
              <caption className="sr-only">Newly failing tests</caption>
              <thead><tr><th scope="col">Test</th><th scope="col">Branch</th><th scope="col">Failing since</th>
                <th scope="col" className="hide-narrow">Last passed</th><th scope="col" className="num">Failures</th><th scope="col" className="hide-narrow">Headline</th></tr></thead>
              <tbody>{g.newly_failing.items.map((t) => (
                <tr key={`${t.test_key}|${t.branch}`}>
                  <td className="wrap-anywhere"><Link to={history(t)}>{testLabel(t)}</Link></td>
                  <td>{t.branch ?? <span className="muted">no branch</span>}</td>
                  <td>{run(t.failing_since_run_id, `${when.format(new Date(t.failing_since))} (run #${t.failing_since_run_id})`)}</td>
                  <td className="hide-narrow">{run(t.last_passed_run_id, when.format(new Date(t.last_passed_at)))}</td>
                  <td className="num">{formatCount(t.failures)}</td>
                  <td className="wrap-anywhere hide-narrow">{t.headline ?? "(no message)"}</td>
                </tr>
              ))}</tbody>
            </table>
            )}
            {more(g.newly_failing.total, g.newly_failing.items.length)}

            <h3>Fixed</h3>
            {g.fixed.items.length === 0 ? <p className="muted">None in this period.</p> : (
            <table className="data">
              <caption className="sr-only">Fixed tests</caption>
              <thead><tr><th scope="col">Test</th><th scope="col">Branch</th><th scope="col">Fixed at</th>
                <th scope="col" className="hide-narrow">Failing since</th><th scope="col" className="num">Time to fix</th></tr></thead>
              <tbody>{g.fixed.items.map((t) => (
                <tr key={`${t.test_key}|${t.branch}`}>
                  <td className="wrap-anywhere"><Link to={history(t)}>{testLabel(t)}</Link></td>
                  <td>{t.branch ?? <span className="muted">no branch</span>}</td>
                  <td>{run(t.fixed_run_id, `${when.format(new Date(t.fixed_at))} (run #${t.fixed_run_id})`)}</td>
                  <td className="hide-narrow">{since(t.failing_since, t.failing_since_bounded)}</td>
                  <td className="num">{t.failing_since_bounded ? "at least " : ""}{formatSpan(t.time_to_fix_ms)}</td>
                </tr>
              ))}</tbody>
            </table>
            )}
            {more(g.fixed.total, g.fixed.items.length)}

            <h3>Longest failing</h3>
            {g.longest_failing.items.length === 0 ? <p className="muted">None in this period.</p> : (
            <table className="data">
              <caption className="sr-only">Longest failing tests</caption>
              <thead><tr><th scope="col">Test</th><th scope="col">Branch</th><th scope="col">Failing since</th>
                <th scope="col" className="num">Consecutive failures</th><th scope="col" className="hide-narrow">Headline</th></tr></thead>
              <tbody>{g.longest_failing.items.map((t) => (
                <tr key={`${t.test_key}|${t.branch}`}>
                  <td className="wrap-anywhere"><Link to={history(t)}>{testLabel(t)}</Link></td>
                  <td>{t.branch ?? <span className="muted">no branch</span>}</td>
                  <td>{since(t.failing_since, t.failing_since_bounded)}</td>
                  <td className="num">{run(t.last_run_id, formatCount(t.consecutive_failures))}</td>
                  <td className="wrap-anywhere hide-narrow">{t.headline ?? "(no message)"}</td>
                </tr>
              ))}</tbody>
            </table>
            )}
            {more(g.longest_failing.total, g.longest_failing.items.length)}
          </>
        );
      }}
    </ReportSection>
  );
}
