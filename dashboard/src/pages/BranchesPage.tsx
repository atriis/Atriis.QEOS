import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatPassRate, getTrends } from "../api/analytics";
import { branchesViewQuery } from "../lib/healthQueries";
import ErrorBanner from "../components/ErrorBanner";
import NarrowMeta from "../components/NarrowMeta";
import FilterBar from "../components/FilterBar";
import { DataTableDisclosure, LegendSeries, SeriesLegend } from "../components/ChartKit";
import { SkeletonCard } from "../components/Skeleton";
import { formatPointLabel, formatTick } from "../lib/chartFormat";
import { useMediaQuery } from "../lib/useMediaQuery";
import SortableTh from "../components/SortableTh";
import { nextSort, parseSort, sortPatch, sortRows, SortState } from "../lib/sort";
import { oneOf, useUrlState } from "../lib/useUrlState";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const axisTick = { fill: "var(--text-secondary)", fontSize: 12 } as const;
const tooltipStyles = {
  contentStyle: { background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 },
  itemStyle: { color: "var(--text-primary)" },
  labelStyle: { color: "var(--text-secondary)" },
} as const;

function useBranchTrend(projectId: number, days: number, tz: string, branch: string) {
  return useQuery({
    queryKey: ["trends", projectId, days, branch, "", "compare"],
    queryFn: () => getTrends(projectId, { days, tz, branch }),
    enabled: branch !== "",
  });
}

const DEFAULTS = { days: "30", a: "", b: "", sort: "last", dir: "" } as const;
const SORT_KEYS = ["branch", "runs", "rate", "failed", "last"] as const;
type SortKey = (typeof SORT_KEYS)[number];
const DEFAULT_SORT: SortState<SortKey> = { key: "last", dir: "desc" };
const DAYS = ["7", "30", "90"] as const;

/** The page with its header (direct use and tests). */
export default function BranchesPage() {
  return (
    <>
      <PageHeader title="Branches" />
      <BranchesView />
    </>
  );
}

/** The view without its header: the shell loads it lazily under an already rendered PageHeader, so the h1 keeps focus. */
export function BranchesView() {
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const { projectId } = useParams();
  const id = Number(projectId);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const { values, update } = useUrlState(DEFAULTS, 1);
  const days = Number(oneOf(values.days, DAYS, "30"));
  const branchA = values.a;
  const branchB = values.b;
  const sort = parseSort(values.sort, values.dir, SORT_KEYS, DEFAULT_SORT);
  const onSort = (key: SortKey) => {
    const next = nextSort(sort, key, key === "branch" ? "asc" : "desc");
    update(sortPatch(next, DEFAULT_SORT));
  };

  const branchesQuery = useQuery(branchesViewQuery(id, days));

  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const narrow = useMediaQuery("(max-width: 640px)");
  const toggleSeries = (key: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const trendA = useBranchTrend(id, days, tz, branchA);
  const trendB = useBranchTrend(id, days, tz, branchB);

  const rows = sortRows(branchesQuery.data ?? [], sort, (r, key) =>
    key === "branch" ? r.branch : key === "runs" ? r.runs : key === "rate" ? r.pass_rate : key === "failed" ? r.failed : Date.parse(r.last_seen));
  const named = rows.filter((r) => r.branch !== null);

  // One row per date, each series in its own key; nulls leave gaps.
  const compareData = (() => {
    if (!trendA.data || !trendB.data) return [];
    const byDate = new Map<string, { date: string; a: number | null; b: number | null }>();
    for (const d of trendA.data.days) {
      byDate.set(d.date, { date: d.date, a: d.pass_rate === null ? null : d.pass_rate * 100, b: null });
    }
    for (const d of trendB.data.days) {
      const row = byDate.get(d.date) ?? { date: d.date, a: null, b: null };
      row.b = d.pass_rate === null ? null : d.pass_rate * 100;
      byDate.set(d.date, row);
    }
    return [...byDate.values()].sort((x, y) => x.date.localeCompare(y.date));
  })();

  const legend: LegendSeries[] = [
    { key: "a", label: branchA, paint: "var(--series-1)", line: {} },
    { key: "b", label: branchB, paint: "var(--series-2)", line: { dash: "6 4" } },
  ];
  const avg = (key: "a" | "b") => {
    const v = compareData.map((d) => d[key]).filter((x): x is number => x !== null);
    return v.length === 0 ? "no runs" : `${(v.reduce((a, b) => a + b, 0) / v.length).toFixed(1)}% on average`;
  };
  const summary = `Pass rate per day over the last ${days} days: ${branchA}, ${avg("a")}; ${branchB}, ${avg("b")}.`;

  return (
    <section>
      <FilterBar>
        <label>
          Days
          <select value={String(days)} onChange={(e) => update({ days: e.target.value })}>
            <option value={7}>7</option>
            <option value={30}>30</option>
            <option value={90}>90</option>
          </select>
        </label>
        <label>
          Compare A
          <select value={branchA} onChange={(e) => update({ a: e.target.value })}>
            <option value="">—</option>
            {named.map((r) => (
              <option key={r.branch} value={r.branch!}>{r.branch}</option>
            ))}
          </select>
        </label>
        <label>
          Compare B
          <select value={branchB} onChange={(e) => update({ b: e.target.value })}>
            <option value="">—</option>
            {named.map((r) => (
              <option key={r.branch} value={r.branch!}>{r.branch}</option>
            ))}
          </select>
        </label>
      </FilterBar>

      {branchesQuery.error != null && (
        <ErrorBanner error={branchesQuery.error} onRetry={() => branchesQuery.refetch()} />
      )}
      {branchesQuery.isPending && <p className="muted">Loading branches…</p>}
      {branchesQuery.data && rows.length === 0 && (
        <p className="muted">No branches with runs in the last {days} days.</p>
      )}

      {branchA && branchB && (
        <div className="card">
          <h2 id="branch-compare">Pass rate per day: {branchA} vs {branchB}</h2>
          {(trendA.error != null || trendB.error != null) && (
            <ErrorBanner error={trendA.error ?? trendB.error} />
          )}
          {(trendA.isPending || trendB.isPending) && trendA.error == null && trendB.error == null ? (
            <SkeletonCard height={220} className="skeleton-chart" />
          ) : compareData.length === 0 ? (
            <p className="muted">No runs on {branchA} or {branchB} in the last {days} days.</p>
          ) : (
            <>
              <SeriesLegend series={legend} hidden={hidden} onToggle={toggleSeries} label="Show or hide a branch" />
              <figure className="chart-figure" aria-labelledby="branch-compare">
                <figcaption className="sr-only">{summary}</figcaption>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={compareData} accessibilityLayer>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="date" stroke="var(--text-muted)" tick={axisTick} tickLine={false} tickFormatter={(v) => formatTick(String(v))} minTickGap={narrow ? 36 : 16} interval="preserveStartEnd" />
                    <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} stroke="var(--text-muted)" tick={axisTick} tickLine={false} width={narrow ? 40 : 48} />
                    <Tooltip
                      {...tooltipStyles}
                      labelFormatter={(v) => formatPointLabel(String(v))}
                      cursor={{ stroke: "var(--grid)" }}
                      formatter={(v) => `${Number(v).toFixed(1)}%`}
                    />
                    <Line dataKey="a" name={branchA} stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} hide={hidden.has("a")} connectNulls={false} />
                    <Line dataKey="b" name={branchB} stroke="var(--series-2)" strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3, strokeWidth: 1.5 }} hide={hidden.has("b")} connectNulls={false} />
                  </LineChart>
                </ResponsiveContainer>
              </figure>
              <DataTableDisclosure name={`pass rate of ${branchA} and ${branchB}`}>
                <table className="data">
                  <thead>
                    <tr><th>Date</th><th className="num">{branchA}</th><th className="num">{branchB}</th></tr>
                  </thead>
                  <tbody>
                    {compareData.map((d) => (
                      <tr key={d.date}>
                        <td>{d.date}</td>
                        <td className="num">{d.a === null ? "—" : `${d.a.toFixed(1)}%`}</td>
                        <td className="num">{d.b === null ? "—" : `${d.b.toFixed(1)}%`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableDisclosure>
            </>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <div ref={card.ref} className={tableCardClass(card.wide)} tabIndex={0} role="region" aria-label="Branches">
          <table className="data">
            <thead>
              <tr>
                <SortableTh label="Branch" sortKey="branch" sort={sort} onSort={onSort} />
                <SortableTh label="Runs" sortKey="runs" sort={sort} onSort={onSort} className="num" />
                <SortableTh label="Pass rate" sortKey="rate" sort={sort} onSort={onSort} className="num" />
                <th className="hide-narrow num">Passed</th>
                <SortableTh label="Failed" sortKey="failed" sort={sort} onSort={onSort} className="num" />
                <th className="hide-narrow num">Errored</th><th className="hide-narrow num">Skipped</th>
                <SortableTh label="Last run" sortKey="last" sort={sort} onSort={onSort} className="hide-narrow" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.branch ?? "(none)"}>
                  <td>
                    {r.branch ?? <span className="muted">no branch</span>}
                    <NarrowMeta items={[
                      { label: "Passed", value: r.passed },
                      { label: "Errored", value: r.errored },
                      { label: "Skipped", value: r.skipped },
                      { label: "Last run", value: new Date(r.last_seen).toLocaleString() },
                    ]} />
                  </td>
                  <td className="num">{r.runs}</td>
                  <td className="num">{formatPassRate(r.pass_rate)}</td>
                  <td className="hide-narrow num">{r.passed}</td>
                  <td className="num">{r.failed}</td>
                  <td className="hide-narrow num">{r.errored}</td>
                  <td className="hide-narrow num">{r.skipped}</td>
                  <td className="hide-narrow">{new Date(r.last_seen).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
