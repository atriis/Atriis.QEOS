import { useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCount, formatDuration, formatPassRate } from "../../../api/analytics";
import { type Report, testLabel } from "../../../api/report";
import { DataTableDisclosure, type LegendSeries, PATTERN, SeriesLegend } from "../../../components/ChartKit";
import NarrowMeta from "../../../components/NarrowMeta";
import { formatPointLabel, formatTick } from "../../../lib/chartFormat";
import { downloadCsv, toCsv } from "../../../lib/csv";
import { pointsDelta, relativeDelta } from "../../../lib/reportDelta";
import DeltaTile from "../DeltaTile";
import ReportSection, { type SectionQuery } from "../ReportSection";
import type { FilterKey } from "../useReportFilters";
import type { Gate } from "../useReportRequest";

const axisTick = { fill: "var(--text-secondary)", fontSize: 12 } as const;
const tooltipStyles = {
  contentStyle: { background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 },
  itemStyle: { color: "var(--text-primary)" },
  labelStyle: { color: "var(--text-secondary)" },
} as const;

const STATUS = [
  { key: "passed", label: "Passed", paint: "var(--status-passed)" },
  { key: "failed", label: "Failed", paint: `url(#${PATTERN.failed})` },
  { key: "errored", label: "Errored", paint: `url(#${PATTERN.errored})` },
  { key: "skipped", label: "Skipped", paint: `url(#${PATTERN.skipped})` },
] as const;
const LEGEND: LegendSeries[] = [
  ...STATUS.map((s) => ({ key: s.key, label: s.label, paint: s.paint })),
  { key: "rate", label: "Pass rate", paint: "var(--series-1)", line: {} },
  { key: "previousRate", label: "Pass rate, previous period", paint: "var(--series-2)", line: { dash: "5 4" } },
];

type Patch = Partial<Record<FilterKey, string>>;
const pct = (rate: number | null) => (rate === null ? null : Math.round(rate * 1000) / 10);

export function bucketsCsv(r: Report): string {
  const s = r.summary!;
  return toCsv(
    ["date", "runs", "executions", "passed", "failed", "errored", "skipped", "pass_rate", "previous_date", "previous_runs", "previous_pass_rate"],
    s.buckets.map((b, i) => {
      const p = s.previous_buckets[i];
      return [b.date, b.runs, b.executions, b.passed, b.failed, b.errored, b.skipped, b.pass_rate,
        p?.date ?? null, p?.runs ?? null, p?.pass_rate ?? null];
    }),
  );
}

export function testsCsv(r: Report): string {
  const s = r.summary!;
  return toCsv(
    ["list", "suite", "class_name", "name", "test_key", "executions", "failures", "pass_rate", "avg_duration_ms"],
    [
      ...s.top_failing.map((t) => ["most failing", t.suite, t.class_name, t.name, t.test_key, t.executions, t.failures, t.pass_rate, null]),
      ...s.slowest.map((t) => ["slowest", t.suite, t.class_name, t.name, t.test_key, t.executions, null, null, t.avg_duration_ms]),
    ],
  );
}

export function branchesCsv(r: Report): string {
  return toCsv(["branch", "runs", "executions", "failures", "pass_rate"],
    r.summary!.branches.map((b) => [b.branch, b.runs, b.executions, b.failures, b.pass_rate]));
}

/** Up to three ways out of an empty result, from the period's busiest values (facets ignore the other filters). */
export function suggestions(r: Report, branch: string | null, environment: string): { label: string; patch: Patch }[] {
  const facets = r.summary?.facets;
  if (!facets) return [];
  return [
    ...facets.branches.filter((b) => b !== branch).map((b) => ({ label: `Try branch ${b}`, patch: { branch: b } })),
    ...facets.environments.filter((e) => e !== environment).map((e) => ({ label: `Try environment ${e}`, patch: { env: e } })),
  ].slice(0, 3);
}

function csvButton(label: string, filename: string, csv: () => string) {
  return (
    <button type="button" onClick={() => downloadCsv(filename, csv())}>
      <Download size={15} aria-hidden="true" /> {label}
    </button>
  );
}

interface Props {
  projectId: number;
  gate: Gate;
  query: SectionQuery;
  /** The branch the report is on (null: every branch), for the test-history links */
  branch: string | null;
  environment: string;
  onClearFilters: () => void;
  onTry: (patch: Patch) => void;
}

/** Section 1 (spec: Section 1: Summary): six delta tiles, results per bucket with this and the previous period's
 *  pass rate, and the most failing, slowest and branch tables, all under the page's filters. */
export default function SummarySection({ projectId, gate, query, branch, environment, onClearFilters, onTry }: Props) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) => setHidden((h) => {
    const next = new Set(h);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const file = (r: Report, part: string) => `report-${projectId}-${r.period.from}-${r.period.to}-${part}.csv`;
  const history = (key: string) =>
    `/projects/${projectId}/tests/${encodeURIComponent(key)}${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`;

  return (
    <ReportSection
      id="report-summary"
      title="Summary"
      gate={gate}
      query={query}
      height={420}
      onResetFilters={onClearFilters}
      actions={query.data?.summary && query.data.scope.runs > 0 ? (
        <>
          {csvButton("Buckets CSV", file(query.data, "buckets"), () => bucketsCsv(query.data!))}
          {csvButton("Tests CSV", file(query.data, "tests"), () => testsCsv(query.data!))}
          {csvButton("Branches CSV", file(query.data, "branches"), () => branchesCsv(query.data!))}
        </>
      ) : undefined}
      noRuns={(r) => (
        <div className="button-row no-print">
          <button type="button" onClick={onClearFilters}>Clear filters</button>
          {suggestions(r, branch, environment).map((s) => (
            <button type="button" key={s.label} onClick={() => onTry(s.patch)}>{s.label}</button>
          ))}
        </div>
      )}
    >
      {(r) => {
        const s = r.summary!;
        const cur = s.current;
        const prev = s.previous;
        const days = r.period.days;
        const failures = cur.failed + cur.errored;
        const prevFailures = prev ? prev.failed + prev.errored : null;
        const unit = r.bucket;
        const rows = s.buckets.map((b, i) => ({
          date: b.date, passed: b.passed, failed: b.failed, errored: b.errored, skipped: b.skipped,
          rate: pct(b.pass_rate), previousRate: pct(s.previous_buckets[i]?.pass_rate ?? null),
        }));
        const worst = [...s.buckets].sort((a, b) => (b.failed + b.errored) - (a.failed + a.errored))[0];
        const caption = `${formatCount(cur.executions)} executions in ${formatCount(cur.runs)} runs, pass rate ${formatPassRate(cur.pass_rate)}`
          + (prev ? `, ${formatPassRate(prev.pass_rate)} in the previous period.` : ", no data in the previous period.")
          + (worst && worst.failed + worst.errored > 0
            ? ` Most failures on ${formatPointLabel(worst.date, unit)}: ${formatCount(worst.failed + worst.errored)}.` : "");
        return (
          <>
            <ul className="kpi-tiles report-tiles" aria-label="Summary figures">
              <li><DeltaTile title="Runs" value={formatCount(cur.runs)} noPrevious={!prev}
                delta={relativeDelta(cur.runs, prev?.runs ?? null, days, "neither")} /></li>
              <li><DeltaTile title="Executions" value={formatCount(cur.executions)} noPrevious={!prev}
                delta={relativeDelta(cur.executions, prev?.executions ?? null, days, "neither")} /></li>
              <li><DeltaTile title="Pass rate" value={formatPassRate(cur.pass_rate)} noPrevious={!prev}
                delta={pointsDelta(cur.pass_rate, prev?.pass_rate ?? null, days, "up")} /></li>
              <li><DeltaTile title="Failures" value={formatCount(failures)} noPrevious={!prev}
                delta={relativeDelta(failures, prevFailures, days, "down")} /></li>
              <li><DeltaTile title="Failing tests" value={formatCount(cur.failing_tests)} noPrevious={!prev}
                delta={relativeDelta(cur.failing_tests, prev?.failing_tests ?? null, days, "down")} /></li>
              <li><DeltaTile title="Average run time" value={formatDuration(cur.avg_run_duration_ms)} noPrevious={!prev}
                delta={relativeDelta(cur.avg_run_duration_ms, prev?.avg_run_duration_ms ?? null, days, "down")} /></li>
            </ul>
            <p className="muted report-note">Pass rate leaves skipped tests out: passed ÷ (executions − skipped).</p>

            <h3 id="summary-chart">Results per {unit}</h3>
            <SeriesLegend series={LEGEND} hidden={hidden} onToggle={toggle} label="Show or hide a series" />
            <figure className="chart-figure" aria-labelledby="summary-chart">
              <figcaption className="sr-only">{caption}</figcaption>
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart data={rows} barCategoryGap="20%" accessibilityLayer>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" stroke="var(--text-muted)" tick={axisTick} tickLine={false}
                    tickFormatter={(d: string) => formatTick(d, unit)} minTickGap={16} interval="preserveStartEnd" />
                  <YAxis yAxisId="count" allowDecimals={false} stroke="var(--text-muted)" tick={axisTick} tickLine={false} width={48} />
                  <YAxis yAxisId="rate" orientation="right" domain={[0, 100]} tickFormatter={(v: number) => `${v}%`}
                    stroke="var(--text-muted)" tick={axisTick} tickLine={false} width={44} />
                  <Tooltip {...tooltipStyles} labelFormatter={(d) => formatPointLabel(String(d), unit)} />
                  {STATUS.map((st, i) => (
                    <Bar key={st.key} yAxisId="count" dataKey={st.key} name={st.label} stackId="status" fill={st.paint}
                      hide={hidden.has(st.key)} stroke="var(--surface-1)" strokeWidth={1}
                      radius={i === STATUS.length - 1 ? [4, 4, 0, 0] : undefined} />
                  ))}
                  <Line yAxisId="rate" dataKey="rate" name="Pass rate" stroke="var(--series-1)" strokeWidth={2} hide={hidden.has("rate")}
                    dot={{ r: 2.5, fill: "var(--series-1)", stroke: "var(--surface-1)" }} connectNulls={false} />
                  <Line yAxisId="rate" dataKey="previousRate" name="Pass rate, previous period" stroke="var(--series-2)" strokeWidth={2}
                    strokeDasharray="5 4" hide={hidden.has("previousRate")}
                    dot={{ r: 2.5, fill: "var(--series-2)", stroke: "var(--surface-1)" }} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </figure>
            <DataTableDisclosure name={`results per ${unit}`}>
              <table className="data">
                <caption className="sr-only">Results per {unit}</caption>
                <thead><tr>
                  <th scope="col">{unit === "day" ? "Date" : "Week of"}</th><th scope="col" className="num">Runs</th>
                  <th scope="col" className="num">Executions</th><th scope="col" className="num">Passed</th>
                  <th scope="col" className="num">Failed</th><th scope="col" className="num">Errored</th>
                  <th scope="col" className="num">Skipped</th><th scope="col" className="num">Pass rate</th>
                  <th scope="col" className="num">Previous period</th>
                </tr></thead>
                <tbody>
                  {s.buckets.map((b, i) => (
                    <tr key={b.date}>
                      <td>{formatPointLabel(b.date, unit)}</td><td className="num">{formatCount(b.runs)}</td>
                      <td className="num">{formatCount(b.executions)}</td><td className="num">{formatCount(b.passed)}</td>
                      <td className="num">{formatCount(b.failed)}</td><td className="num">{formatCount(b.errored)}</td>
                      <td className="num">{formatCount(b.skipped)}</td><td className="num">{formatPassRate(b.pass_rate)}</td>
                      <td className="num">{formatPassRate(s.previous_buckets[i]?.pass_rate ?? null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableDisclosure>

            <h3>Most failing tests (top 10)</h3>
            {s.top_failing.length === 0 ? <p className="muted">No failures in this period.</p> : (
              <table className="data">
                <caption className="sr-only">Most failing tests</caption>
                <thead><tr><th scope="col">Test</th><th scope="col" className="num hide-narrow">Executions</th>
                  <th scope="col" className="num">Failures</th><th scope="col" className="num">Pass rate</th></tr></thead>
                <tbody>
                  {s.top_failing.map((t) => (
                    <tr key={t.test_key}>
                      <td className="wrap-anywhere">
                        <Link to={history(t.test_key)}>{testLabel(t)}</Link>
                        <NarrowMeta items={[{ label: "Executions", value: formatCount(t.executions) }]} />
                      </td>
                      <td className="num hide-narrow">{formatCount(t.executions)}</td>
                      <td className="num">{formatCount(t.failures)}</td>
                      <td className="num">{formatPassRate(t.pass_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <h3>Slowest tests (top 10)</h3>
            <table className="data">
              <caption className="sr-only">Slowest tests</caption>
              <thead><tr><th scope="col">Test</th><th scope="col" className="num hide-narrow">Executions</th>
                <th scope="col" className="num">Average duration</th></tr></thead>
              <tbody>
                {s.slowest.map((t) => (
                  <tr key={t.test_key}>
                    <td className="wrap-anywhere">
                      <Link to={history(t.test_key)}>{testLabel(t)}</Link>
                      <NarrowMeta items={[{ label: "Executions", value: formatCount(t.executions) }]} />
                    </td>
                    <td className="num hide-narrow">{formatCount(t.executions)}</td>
                    <td className="num">{formatDuration(t.avg_duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Branches (top 10)</h3>
            <table className="data">
              <caption className="sr-only">Branches</caption>
              <thead><tr><th scope="col">Branch</th><th scope="col" className="num">Runs</th>
                <th scope="col" className="num hide-narrow">Executions</th><th scope="col" className="num">Failures</th>
                <th scope="col" className="num">Pass rate</th></tr></thead>
              <tbody>
                {s.branches.map((b) => (
                  <tr key={b.branch ?? "(none)"}>
                    <td>
                      {b.branch ?? <span className="muted">no branch</span>}
                      <NarrowMeta items={[{ label: "Executions", value: formatCount(b.executions) }]} />
                    </td>
                    <td className="num">{formatCount(b.runs)}</td>
                    <td className="num hide-narrow">{formatCount(b.executions)}</td>
                    <td className="num">{formatCount(b.failures)}</td>
                    <td className="num">{formatPassRate(b.pass_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        );
      }}
    </ReportSection>
  );
}
