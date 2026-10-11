import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCount, formatPassRate } from "../../../api/analytics";
import type { CaseAreas } from "../../../api/cases";
import { DataTableDisclosure } from "../../../components/ChartKit";
import SortableTh from "../../../components/SortableTh";
import { downloadCsv, toCsv } from "../../../lib/csv";
import NarrowMeta from "../../../components/NarrowMeta";
import { type AreaStats, GROUPINGS, type Grouping, decodeTests, groupByArea } from "../../../lib/reportScope";
import { type SortState, nextSort, sortRows } from "../../../lib/sort";
import ReportSection, { type SectionQuery } from "../ReportSection";
import { useGrouping } from "../useGrouping";
import { type Gate, caseAreasMessage } from "../useReportRequest";

const NAMES: Record<Grouping, string> = { feature: "Feature", folder: "Folder", label: "Label", suite: "Suite" };
const WORST_IN_CHART = 15;
type Col = "label" | "linkedTests" | "testsRun" | "executions" | "passRate" | "failures" | "failingTests" | "flakyTests";
const TEXT_COLS: Col[] = ["label"];

export function casesLink(projectId: number, g: AreaStats): string {
  const [kind, ...rest] = g.key.split(":");
  const value = rest.join(":");
  if (kind === "suite") return `/projects/${projectId}/suites/${value}`;
  return `/projects/${projectId}/cases?${kind}=${encodeURIComponent(value)}`;
}

export function areasCsv(groups: AreaStats[], noCase: AreaStats | null): string {
  return toCsv(["area", "linked_tests", "tests_run", "executions", "pass_rate", "failures", "failing_tests", "flaky_tests", "few_runs"],
    [...groups, ...(noCase ? [noCase] : [])].map((g) => [g.label, g.linkedTests, g.testsRun, g.executions, g.passRate,
      g.failures, g.failingTests, g.flakyTests, String(g.fewRuns)]));
}

/** The grouping control shared by Sections 3 and 5: a segmented group of pressed buttons, plus a depth for folders. */
export function GroupingControl({ areas }: { areas?: CaseAreas }) {
  const { grouping, depth, deepest, setGrouping, setDepth } = useGrouping(areas);
  const labelId = useId();
  return (
    <div className="report-grouping no-print">
      <div className="segmented-field">
        <span id={labelId} className="segmented-label">Group by</span>
        <div role="group" aria-labelledby={labelId} className="segmented">
          {GROUPINGS.map((g) => (
            <button key={g} type="button" aria-pressed={grouping === g} onClick={() => setGrouping(g)}>{NAMES[g]}</button>
          ))}
        </div>
      </div>
      {grouping === "folder" && (
        <label>Depth
          <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
            {Array.from({ length: deepest }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}

interface Props {
  projectId: number;
  gate: Gate;
  query: SectionQuery;
  caseAreas: { data?: CaseAreas; error: unknown; refetch: () => unknown };
  onResetFilters: () => void;
}

/** Section 3 (spec: Section 3: By area): ingestion's per-test rows grouped by the cases' feature, folder, label or
 *  suite in the dashboard (ADR-026). */
export default function AreaSection({ projectId, gate, query, caseAreas, onResetFilters }: Props) {
  const { grouping, depth } = useGrouping(caseAreas.data);
  const [sort, setSort] = useState<SortState<Col> | null>(null);
  const blocked = caseAreas.error != null;
  const sectionGate: Gate = blocked
    ? { state: "blocked", message: caseAreasMessage(caseAreas.error), error: caseAreas.error, retry: () => void caseAreas.refetch() }
    : !caseAreas.data && gate.state === "ready" ? { state: "wait" } : gate;

  return (
    <ReportSection
      id="report-areas"
      title="By area"
      gate={sectionGate}
      query={query}
      height={380}
      onResetFilters={onResetFilters}
      actions={<GroupingControl areas={caseAreas.data} />}
    >
      {(r) => {
        const tests = r.tests;
        const areas = caseAreas.data;
        if (!tests || !areas) return null;
        const cut = tests.truncated;
        const grouped = groupByArea(areas, decodeTests(tests), grouping, depth);
        const groups = grouped.groups;
        // A test that ran but fell past the row cap would look unlinked, so the count is not shown as a fact.
        const noCase = cut ? null : grouped.noCase;
        const shown = sort ? sortRows(groups, sort, (g, k) => g[k]) : groups;
        const worst = groups.filter((g) => !g.fewRuns && g.passRate !== null).slice(0, WORST_IN_CHART);
        const chart = worst.map((g) => ({ label: g.label, rate: Math.round((g.passRate ?? 0) * 1000) / 10, failures: g.failures }));
        const caption = worst.length
          ? `${worst.length} areas with at least 10 executions; the lowest pass rate is ${worst[0].label} at ${formatPassRate(worst[0].passRate)} with ${formatCount(worst[0].failures)} failures.`
          : "No area has 10 or more executions in this period.";
        const onSort = (key: Col) => setSort(nextSort(sort ?? { key: "passRate", dir: "asc" }, key, TEXT_COLS.includes(key) ? "asc" : "desc"));
        return (
          <>
            {(grouping === "label" || grouping === "suite") && (
              <p className="muted report-note">A test in several {grouping === "label" ? "labels" : "suites"} counts in each: the groups overlap and are not summed.</p>
            )}
            {cut && (
              <p className="muted report-note">
                More than 50,000 tests ran; only the 50,000 with the most failures are grouped.
                {" "}Never-run and unlinked counts are hidden because the list was cut at 50,000 tests.
              </p>
            )}
            {worst.length === 0 ? <p className="muted">{caption}</p> : (
              <>
                <figure className="chart-figure" aria-labelledby="report-areas">
                  <figcaption className="sr-only">{caption}</figcaption>
                  <ResponsiveContainer width="100%" height={Math.max(160, chart.length * 28)}>
                    <BarChart data={chart} layout="vertical" margin={{ left: 8, right: 64 }} accessibilityLayer>
                      <CartesianGrid stroke="var(--grid)" horizontal={false} />
                      <XAxis type="number" domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} stroke="var(--text-muted)" tick={{ fill: "var(--text-secondary)", fontSize: 12 }} />
                      <YAxis type="category" dataKey="label" width={200} stroke="var(--text-muted)" tick={{ fill: "var(--text-secondary)", fontSize: 12 }} />
                      <Tooltip contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 }} />
                      <Bar dataKey="rate" name="Pass rate (%)" fill="var(--series-1)" radius={[0, 4, 4, 0]}>
                        <LabelList dataKey="failures" position="right" fill="var(--text-secondary)" fontSize={12}
                          formatter={(v: number) => `${formatCount(v)} failures`} />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </figure>
                <DataTableDisclosure name="pass rate of the worst areas">
                  <table className="data">
                    <thead><tr><th scope="col">Area</th><th scope="col" className="num">Pass rate</th><th scope="col" className="num">Failures</th></tr></thead>
                    <tbody>{worst.map((g) => <tr key={g.key}><td>{g.label}</td><td className="num">{formatPassRate(g.passRate)}</td><td className="num">{formatCount(g.failures)}</td></tr>)}</tbody>
                  </table>
                </DataTableDisclosure>
              </>
            )}
            <div className="button-row no-print">
              <button type="button" onClick={() => downloadCsv(`report-${projectId}-${r.period.from}-${r.period.to}-areas.csv`, areasCsv(groups, noCase))}>
                <Download size={15} aria-hidden="true" /> Areas CSV
              </button>
            </div>
            <table className="data">
              <caption className="sr-only">By area ({NAMES[grouping].toLowerCase()})</caption>
              <thead><tr>
                <SortableTh label="Area" sortKey="label" sort={sort} onSort={onSort} />
                <SortableTh label="Linked tests" sortKey="linkedTests" sort={sort} onSort={onSort} className="num hide-narrow" />
                <SortableTh label="Tests run" sortKey="testsRun" sort={sort} onSort={onSort} className="num hide-narrow" />
                <SortableTh label="Executions" sortKey="executions" sort={sort} onSort={onSort} className="num" />
                <SortableTh label="Pass rate" sortKey="passRate" sort={sort} onSort={onSort} className="num" />
                <SortableTh label="Failures" sortKey="failures" sort={sort} onSort={onSort} className="num" />
                <SortableTh label="Failing tests" sortKey="failingTests" sort={sort} onSort={onSort} className="num hide-narrow" />
                <SortableTh label="Flaky tests" sortKey="flakyTests" sort={sort} onSort={onSort} className="num hide-narrow" />
              </tr></thead>
              <tbody>
                {shown.map((g) => (
                  <tr key={g.key}>
                    <td className="wrap-anywhere">
                      <Link to={casesLink(projectId, g)}>{g.label}</Link>
                      {g.fewRuns && <span className="muted"> · few runs</span>}
                      <NarrowMeta items={[
                        { label: "Tests run", value: formatCount(g.testsRun) },
                        { label: "Failing tests", value: formatCount(g.failingTests) },
                        { label: "Flaky tests", value: formatCount(g.flakyTests) },
                      ]} />
                    </td>
                    <td className="num hide-narrow">{formatCount(g.linkedTests)}</td>
                    <td className="num hide-narrow">{formatCount(g.testsRun)}</td>
                    <td className="num">{formatCount(g.executions)}</td>
                    <td className="num">{formatPassRate(g.passRate)}</td>
                    <td className="num">{formatCount(g.failures)}</td>
                    <td className="num hide-narrow">{formatCount(g.failingTests)}</td>
                    <td className="num hide-narrow">{formatCount(g.flakyTests)}</td>
                  </tr>
                ))}
                {noCase && (
                  <tr>
                    <td>
                      <span className="muted">Tests without a case</span>
                      <NarrowMeta items={[
                        { label: "Tests run", value: formatCount(noCase.testsRun) },
                        { label: "Failing tests", value: formatCount(noCase.failingTests) },
                        { label: "Flaky tests", value: formatCount(noCase.flakyTests) },
                      ]} />
                    </td>
                    <td className="num hide-narrow">—</td>
                    <td className="num hide-narrow">{formatCount(noCase.testsRun)}</td>
                    <td className="num">{formatCount(noCase.executions)}</td>
                    <td className="num">{formatPassRate(noCase.passRate)}</td>
                    <td className="num">{formatCount(noCase.failures)}</td>
                    <td className="num hide-narrow">{formatCount(noCase.failingTests)}</td>
                    <td className="num hide-narrow">{formatCount(noCase.flakyTests)}</td>
                  </tr>
                )}
              </tbody>
            </table>
            <p className="muted report-note">A flaky test here has at least 5 outcomes and flips in at least 30% of consecutive pairs.</p>
          </>
        );
      }}
    </ReportSection>
  );
}
