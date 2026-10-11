import { useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCount, formatDuration } from "../../../api/analytics";
import type { CaseArea, CaseAreas } from "../../../api/cases";
import type { Report } from "../../../api/report";
import { DataTableDisclosure, type LegendSeries, PATTERN, SeriesLegend } from "../../../components/ChartKit";
import NarrowMeta from "../../../components/NarrowMeta";
import { formatPointLabel, formatTick } from "../../../lib/chartFormat";
import { downloadCsv, toCsv } from "../../../lib/csv";
import { type AreaStats, type Grouping, decodeTests, folderAtDepth, groupByArea, neverRun, resolveScope, unlinkedTestCount } from "../../../lib/reportScope";
import DeltaTile from "../DeltaTile";
import ReportSection, { type SectionQuery } from "../ReportSection";
import { GroupingControl } from "./AreaSection";
import { useGrouping } from "../useGrouping";
import type { ReportFilters } from "../useReportFilters";
import { type Gate, caseAreasMessage } from "../useReportRequest";

const NEVER_RUN_SHOWN = 200;
const LARGEST_GROUPS = 15;
const axisTick = { fill: "var(--text-secondary)", fontSize: 12 } as const;
const COVERAGE_LEGEND: LegendSeries[] = [
  { key: "linked", label: "Linked (automated)", paint: "var(--series-1)" },
  { key: "manual", label: "Manual (striped)", paint: `url(#${PATTERN.manual})` },
];
const DURATION_LEGEND: LegendSeries[] = [
  { key: "avg", label: "Average", paint: "var(--series-1)", line: { marker: true } },
  { key: "p90", label: "p90 (dashed)", paint: "var(--series-2)", line: { dash: "5 4", marker: true } },
];
const tooltipStyle = { background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 } as const;

export function coverageGroups(areas: CaseAreas, grouping: Grouping, depth: number): { label: string; linked: number; manual: number }[] {
  // Coverage follows Section 3's grouping for feature and folder; labels and suites overlap, so they fall back to feature
  const byFolder = grouping === "folder";
  const counts = new Map<string, { label: string; linked: number; manual: number }>();
  for (const c of areas.cases) {
    const label = byFolder ? (c.folder ? folderAtDepth(c.folder, depth) : "No folder") : (c.feature ?? "No feature");
    const row = counts.get(label) ?? { label, linked: 0, manual: 0 };
    if (c.testKey) row.linked += 1;
    else row.manual += 1;
    counts.set(label, row);
  }
  return [...counts.values()].sort((a, b) => (b.linked + b.manual) - (a.linked + a.manual) || a.label.localeCompare(b.label));
}

export function neverRunCsv(cases: CaseArea[]): string {
  return toCsv(["case", "title", "folder", "feature"], cases.map((c) => [`TC-${c.number}`, c.title, c.folder, c.feature]));
}

export function durationCsv(r: Report): string {
  return toCsv(["date", "runs", "avg_ms", "p50_ms", "p90_ms", "max_ms"],
    (r.duration?.buckets ?? []).map((b) => [b.date, b.runs, b.avg_ms, b.p50_ms, b.p90_ms, b.max_ms]));
}

export function slowestAreasCsv(groups: AreaStats[]): string {
  return toCsv(["area", "duration_ms_sum", "executions", "avg_ms_per_execution"],
    groups.map((g) => [g.label, g.durationMsSum, g.executions, g.executions ? Math.round(g.durationMsSum / g.executions) : null]));
}

interface Props {
  projectId: number;
  gate: Gate;
  testsQuery: SectionQuery;
  durationQuery: SectionQuery;
  caseAreas: { data?: CaseAreas; error: unknown; refetch: () => unknown };
  filters: ReportFilters;
  onResetFilters: () => void;
}

/** Section 5 (spec: Section 5: Coverage and duration). */
export default function CoverageDurationSection({ projectId, gate, testsQuery, durationQuery, caseAreas, filters, onResetFilters }: Props) {
  const { grouping, depth } = useGrouping(caseAreas.data);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) => setHidden((h) => {
    const next = new Set(h);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const sectionGate: Gate = caseAreas.error != null
    ? { state: "blocked", message: caseAreasMessage(caseAreas.error), error: caseAreas.error, retry: () => void caseAreas.refetch() }
    : !caseAreas.data && gate.state === "ready" ? { state: "wait" } : gate;
  // One frame over both requests: an error or loading in either shows here
  // Retry asks again only for the request that failed (both when neither is marked failed)
  const query: SectionQuery = {
    data: testsQuery.data && durationQuery.data ? { ...testsQuery.data, duration: durationQuery.data.duration } : undefined,
    error: testsQuery.error ?? durationQuery.error,
    isPending: testsQuery.isPending || durationQuery.isPending,
    refetch: () => {
      const bothOk = testsQuery.error == null && durationQuery.error == null;
      if (bothOk || testsQuery.error != null) void testsQuery.refetch();
      if (bothOk || durationQuery.error != null) void durationQuery.refetch();
    },
  };
  const file = (r: Report, part: string) => `report-${projectId}-${r.period.from}-${r.period.to}-${part}.csv`;

  return (
    <ReportSection id="report-coverage" title="Coverage and duration" gate={sectionGate} query={query} height={520}
      onResetFilters={onResetFilters} actions={<GroupingControl areas={caseAreas.data} />}>
      {(r) => {
        const areas = caseAreas.data;
        if (!areas) return null;
        const tests = r.tests;
        const d = r.duration;
        // A test cut off by the 50,000-row cap looks never run, so neither list is shown as fact then
        const cut = tests?.truncated === true;
        const rows = tests ? decodeTests(tests) : [];
        const scope = resolveScope(areas, filters.area, filters.suite);
        const missing = tests && !cut ? neverRun(areas, rows, scope) : null;
        const unlinked = tests && !cut ? unlinkedTestCount(areas, rows) : null;
        const coverage = coverageGroups(areas, grouping, depth).slice(0, LARGEST_GROUPS);
        const slowest = tests
          ? groupByArea(areas, rows, grouping, depth).groups.filter((g) => g.executions > 0).sort((a, b) => b.durationMsSum - a.durationMsSum)
          : [];
        const unit = r.bucket;
        const title = d?.basis === "test_time" ? "Time in selected tests (summed)" : "Run time (wall clock)";
        const longest = d ? [...d.buckets].filter((b) => b.avg_ms !== null).sort((a, b) => (b.avg_ms ?? 0) - (a.avg_ms ?? 0))[0] : undefined;
        const durationCaption = longest && d
          ? `Average ${title.toLowerCase()} per ${unit}; the longest is ${formatPointLabel(longest.date, unit)} at ${formatDuration(longest.avg_ms)}`
            + (d.previous?.avg_ms != null ? `, against ${formatDuration(d.previous.avg_ms)} on average in the previous period.` : ".")
          : "No runs to time in this period.";
        return (
          <>
            <ul className="kpi-tiles" aria-label="Coverage figures">
              <li><DeltaTile title="Active cases" value={formatCount(areas.counts.cases)} delta={null} noPrevious={false} /></li>
              <li><DeltaTile title="Linked (automated)" value={formatCount(areas.counts.linked)} delta={null} noPrevious={false} /></li>
              <li><DeltaTile title="Manual" value={formatCount(areas.counts.manual)} delta={null} noPrevious={false} /></li>
              {missing && <li><DeltaTile title="Automated, not run in this period" value={formatCount(missing.length)} delta={null} noPrevious={false} /></li>}
            </ul>

            <h3 id="report-coverage-chart">Linked and manual cases by {grouping === "folder" ? "folder" : "feature"}</h3>
            <SeriesLegend series={COVERAGE_LEGEND} hidden={hidden} onToggle={toggle} label="Show or hide a series in the coverage chart" />
            <figure className="chart-figure" aria-labelledby="report-coverage-chart">
              <figcaption className="sr-only">{`${formatCount(areas.counts.linked)} linked and ${formatCount(areas.counts.manual)} manual cases; the largest group is ${coverage[0]?.label ?? "none"}.`}</figcaption>
              <ResponsiveContainer width="100%" height={Math.max(160, coverage.length * 28)}>
                <BarChart data={coverage} layout="vertical" margin={{ left: 8, right: 24 }} accessibilityLayer>
                  <CartesianGrid stroke="var(--grid)" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} stroke="var(--text-muted)" tick={axisTick} />
                  <YAxis type="category" dataKey="label" width={200} stroke="var(--text-muted)" tick={axisTick} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="linked" name="Linked (automated)" stackId="c" hide={hidden.has("linked")} fill="var(--series-1)" stroke="var(--surface-1)" />
                  <Bar dataKey="manual" name="Manual (striped)" stackId="c" hide={hidden.has("manual")} fill={`url(#${PATTERN.manual})`} stroke="var(--surface-1)" />
                </BarChart>
              </ResponsiveContainer>
            </figure>
            <DataTableDisclosure name="linked and manual cases by group">
              <table className="data">
                <thead><tr><th scope="col">Group</th><th scope="col" className="num">Linked</th><th scope="col" className="num">Manual</th></tr></thead>
                <tbody>{coverage.map((g) => <tr key={g.label}><td>{g.label}</td><td className="num">{formatCount(g.linked)}</td><td className="num">{formatCount(g.manual)}</td></tr>)}</tbody>
              </table>
            </DataTableDisclosure>

            <h3>Automated, not run in this period <span className="muted">(under the current filters)</span></h3>
            {!tests ? <p className="muted">Per-test numbers are not in this response.</p>
              : !missing || unlinked === null ? (
                <p className="muted report-note">The never-run list and the count of tests without a case are hidden because the list was cut at 50,000 tests.</p>
              ) : (
                <>
                  {missing.length === 0 ? <p className="muted">Every automated case ran.</p> : (
                    <>
                      <table className="data">
                        <caption className="sr-only">Automated, not run in this period</caption>
                        <thead><tr><th scope="col">Case</th><th scope="col">Title</th><th scope="col" className="hide-narrow">Folder</th><th scope="col" className="hide-narrow">Feature</th></tr></thead>
                        <tbody>{missing.slice(0, NEVER_RUN_SHOWN).map((c) => (
                          <tr key={c.number}>
                            <td>
                              <Link to={`/projects/${projectId}/cases/${c.number}`}>TC-{c.number}</Link>
                              <NarrowMeta items={[{ label: "Folder", value: c.folder }, { label: "Feature", value: c.feature }]} />
                            </td>
                            <td className="wrap-anywhere">{c.title}</td>
                            <td className="hide-narrow">{c.folder ?? "—"}</td>
                            <td className="hide-narrow">{c.feature ?? "—"}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                      {missing.length > NEVER_RUN_SHOWN && <p className="muted report-note">And {formatCount(missing.length - NEVER_RUN_SHOWN)} more (in the CSV).</p>}
                      <div className="button-row no-print">
                        <button type="button" onClick={() => downloadCsv(file(r, "never-run"), neverRunCsv(missing))}><Download size={15} aria-hidden="true" /> Never-run CSV</button>
                      </div>
                    </>
                  )}
                  <p><Link to={`/projects/${projectId}/tests`}>{formatCount(unlinked)} {unlinked === 1 ? "test" : "tests"} without a case</Link> ran in this period.</p>
                </>
              )}

            <h3 id="report-duration">{title}</h3>
            {!d ? <p className="muted">Run times are not in this response.</p> : (
              <>
                <p className="muted report-note">
                  {d.basis === "test_time"
                    ? "Test filters are on, so this is the time spent in the selected tests in each run, not the whole run."
                    : "The wall-clock time of each run, from its start to its end."}
                </p>
                <SeriesLegend series={DURATION_LEGEND} hidden={hidden} onToggle={toggle} label="Show or hide a series in the duration chart" />
                <figure className="chart-figure" aria-labelledby="report-duration">
                  <figcaption className="sr-only">{durationCaption}</figcaption>
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={d.buckets} accessibilityLayer>
                      <CartesianGrid stroke="var(--grid)" vertical={false} />
                      <XAxis dataKey="date" stroke="var(--text-muted)" tick={axisTick} tickLine={false} tickFormatter={(v: string) => formatTick(v, unit)} minTickGap={16} />
                      <YAxis stroke="var(--text-muted)" tick={axisTick} tickLine={false} width={64} tickFormatter={(v: number) => formatDuration(v)} />
                      <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => formatPointLabel(String(v), unit)} formatter={(v) => formatDuration(Number(v))} />
                      {d.previous?.avg_ms != null && (
                        <ReferenceLine y={d.previous.avg_ms} stroke="var(--text-muted)" strokeDasharray="2 4"
                          label={{ value: "Previous average", fill: "var(--text-secondary)", fontSize: 12, position: "insideTopRight" }} />
                      )}
                      <Line dataKey="avg_ms" name="Average" hide={hidden.has("avg")} stroke="var(--series-1)" strokeWidth={2} dot={{ r: 2.5, fill: "var(--series-1)", stroke: "var(--surface-1)" }} connectNulls={false} />
                      <Line dataKey="p90_ms" name="p90" hide={hidden.has("p90")} stroke="var(--series-2)" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 2.5, fill: "var(--series-2)", stroke: "var(--surface-1)" }} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </figure>
                <DataTableDisclosure name={title.toLowerCase()}>
                  <table className="data">
                    <thead><tr><th scope="col">{unit === "day" ? "Date" : "Week of"}</th><th scope="col" className="num">Runs</th><th scope="col" className="num">Average</th>
                      <th scope="col" className="num">p50</th><th scope="col" className="num">p90</th><th scope="col" className="num">Max</th></tr></thead>
                    <tbody>{d.buckets.map((b) => (
                      <tr key={b.date}><td>{formatPointLabel(b.date, unit)}</td><td className="num">{formatCount(b.runs)}</td><td className="num">{formatDuration(b.avg_ms)}</td>
                        <td className="num">{formatDuration(b.p50_ms)}</td><td className="num">{formatDuration(b.p90_ms)}</td><td className="num">{formatDuration(b.max_ms)}</td></tr>
                    ))}</tbody>
                  </table>
                </DataTableDisclosure>
              </>
            )}
            <div className="button-row no-print">
              {d && <button type="button" onClick={() => downloadCsv(file(r, "duration"), durationCsv(r))}><Download size={15} aria-hidden="true" /> Duration CSV</button>}
              {tests && <button type="button" onClick={() => downloadCsv(file(r, "slowest-areas"), slowestAreasCsv(slowest))}><Download size={15} aria-hidden="true" /> Slowest areas CSV</button>}
            </div>

            {tests && (
              <>
                <h3>Slowest areas</h3>
                {slowest.length === 0 ? <p className="muted">No area ran a test in this period.</p> : (
                  <table className="data">
                    <caption className="sr-only">Slowest areas</caption>
                    <thead><tr><th scope="col">Area</th><th scope="col" className="num">Total test time</th><th scope="col" className="num hide-narrow">Executions</th>
                      <th scope="col" className="num">Average per execution</th></tr></thead>
                    <tbody>{slowest.map((g) => (
                      <tr key={g.key}>
                        <td className="wrap-anywhere">
                          {g.label}
                          <NarrowMeta items={[{ label: "Executions", value: formatCount(g.executions) }]} />
                        </td>
                        <td className="num">{formatDuration(g.durationMsSum)}</td>
                        <td className="num hide-narrow">{formatCount(g.executions)}</td>
                        <td className="num">{formatDuration(Math.round(g.durationMsSum / g.executions))}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                )}
              </>
            )}
          </>
        );
      }}
    </ReportSection>
  );
}
