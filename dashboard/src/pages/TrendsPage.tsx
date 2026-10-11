import { FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import { oneOf, useDraft, useUrlState } from "../lib/useUrlState";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { TrendBucket, formatDuration, formatPassRate } from "../api/analytics";
import { trendsViewQuery } from "../lib/healthQueries";
import ErrorBanner from "../components/ErrorBanner";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import FilterBar from "../components/FilterBar";
import { ChartPatternDefs, DataTableDisclosure, LegendSeries, PATTERN, SeriesLegend } from "../components/ChartKit";
import { AXIS_TICK, TOOLTIP_STYLES, formatPointLabel, formatTick } from "../lib/chartFormat";
import PassRateChart from "../components/PassRateChart";
import { useMediaQuery } from "../lib/useMediaQuery";
import PageHeader from "../components/PageHeader";

// Colour plus texture (solid, stripes, dots, lines): the bars stay readable without telling hues apart.
const STATUS = [
  { key: "passed", label: "Passed", paint: "var(--status-passed)" },
  { key: "failed", label: "Failed", paint: `url(#${PATTERN.failed})` },
  { key: "errored", label: "Errored", paint: `url(#${PATTERN.errored})` },
  { key: "skipped", label: "Skipped", paint: `url(#${PATTERN.skipped})` },
] as const;
const LEGEND: LegendSeries[] = STATUS.map((s) => ({ key: s.key, label: s.label, paint: s.paint }));
const NOUN = { day: "day", week: "week", month: "month" } as const;

const DEFAULTS = { days: "30", bucket: "day", branch: "", environment: "" } as const;
const DAYS = ["7", "30", "90"] as const;
const BUCKETS = ["day", "week", "month"] as const;

/** The page with its header (direct use and tests). */
export default function TrendsPage() {
  return (
    <>
      <PageHeader title="Trends" />
      <TrendsView />
    </>
  );
}

/** The view without its header: the shell loads it lazily under an already rendered PageHeader, so the h1 keeps focus. */
export function TrendsView() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const { values, update } = useUrlState(DEFAULTS, 1);
  const days = Number(oneOf(values.days, DAYS, "30"));
  const bucket = oneOf(values.bucket, BUCKETS, "day") as TrendBucket;
  const { branch, environment } = values;
  // Text filters are drafts until Apply: per-keystroke refetching is chatty
  // against the shared gateway rate limit.
  const [branchInput, setBranchInput, commitBranch] = useDraft(branch);
  const [environmentInput, setEnvironmentInput, commitEnvironment] = useDraft(environment);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const narrow = useMediaQuery("(max-width: 640px)");
  const toggleSeries = (key: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    update({ branch: commitBranch((raw) => raw.trim()), environment: commitEnvironment((raw) => raw.trim()) });
  }

  const query = useQuery(trendsViewQuery(id, tz, days, bucket, branch, environment));

  const trendDays = query.data?.days ?? [];
  const totals = trendDays.reduce(
    (acc, d) => ({
      runs: acc.runs + d.runs,
      passed: acc.passed + d.passed,
      counted: acc.counted + d.passed + d.failed + d.errored,
    }),
    { runs: 0, passed: 0, counted: 0 },
  );
  const windowRate = totals.counted > 0 ? totals.passed / totals.counted : null;
  const unit = NOUN[bucket];
  const tick = (v: string) => formatTick(v, bucket);
  const label = (v: unknown) => formatPointLabel(String(v), bucket);
  const sums = trendDays.reduce(
    (a, d) => ({ passed: a.passed + d.passed, failed: a.failed + d.failed, errored: a.errored + d.errored, skipped: a.skipped + d.skipped }),
    { passed: 0, failed: 0, errored: 0, skipped: 0 },
  );
  const worst = trendDays.reduce<(typeof trendDays)[number] | null>((w, d) => (d.failed + d.errored > (w ? w.failed + w.errored : 0) ? d : w), null);
  const resultsSummary =
    `Stacked bars of results per ${unit}, ${formatPointLabel(trendDays[0]?.date ?? "", bucket)} to ${formatPointLabel(trendDays[trendDays.length - 1]?.date ?? "", bucket)}: ` +
    `${sums.passed} passed, ${sums.failed} failed, ${sums.errored} errored, ${sums.skipped} skipped.` +
    (worst ? ` Most failing or errored: ${formatPointLabel(worst.date, bucket)}, ${worst.failed + worst.errored}.` : " No failures.");

  return (
    <section>
      <ChartPatternDefs />
      <form onSubmit={applyFilters}>
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
            View
            <select value={bucket} onChange={(e) => update({ bucket: e.target.value })}>
              <option value="day">Daily</option>
              <option value="week">Weekly</option>
              <option value="month">Monthly</option>
            </select>
          </label>
          <label>
            Branch
            <input value={branchInput} onChange={(e) => setBranchInput(e.target.value)} placeholder="all" />
          </label>
          <label>
            Environment
            <input
              value={environmentInput}
              onChange={(e) => setEnvironmentInput(e.target.value)}
              placeholder="all"
            />
          </label>
          <button type="submit">Apply</button>
        </FilterBar>
      </form>

      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {query.isPending && (
        <SkeletonStatus label="Loading trends…">
          <div className="tiles">
            <SkeletonCard height={34} />
            <SkeletonCard height={34} />
            <SkeletonCard height={34} />
          </div>
          <SkeletonCard height={280} className="skeleton-chart" />
          <SkeletonCard height={180} className="skeleton-chart" />
        </SkeletonStatus>
      )}
      {query.data && trendDays.length === 0 && (
        <p className="muted">
          No runs in the last {days} days{branch && ` on ${branch}`}{environment && ` in ${environment}`}.
        </p>
      )}

      {trendDays.length > 0 && (
        <>
          <div className="tiles">
            <div className="card">
              <div className="tile-value">{totals.runs}</div>
              <div className="tile-label">Runs ({days} days)</div>
            </div>
            <div className="card">
              <div className="tile-value">{formatPassRate(windowRate)}</div>
              <div className="tile-label">Pass rate ({days} days)</div>
            </div>
            <div className="card">
              <div className="tile-value">
                {formatDuration(trendDays[trendDays.length - 1].avg_run_duration_ms)}
              </div>
              <div className="tile-label">Avg run duration (last {unit})</div>
            </div>
          </div>

          <div className="card">
            <h2 id="trend-results">Results per {unit}</h2>
            <SeriesLegend series={LEGEND} hidden={hidden} onToggle={toggleSeries} label="Show or hide a result type" />
            <figure className="chart-figure" aria-labelledby="trend-results">
              <figcaption className="sr-only">{resultsSummary}</figcaption>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={trendDays} barCategoryGap="20%" accessibilityLayer>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" stroke="var(--text-muted)" tick={AXIS_TICK} tickLine={false} tickFormatter={tick} minTickGap={narrow ? 36 : 16} interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} stroke="var(--text-muted)" tick={AXIS_TICK} tickLine={false} width={narrow ? 32 : 48} />
                  <Tooltip {...TOOLTIP_STYLES} labelFormatter={label} cursor={{ fill: "var(--grid)", fillOpacity: 0.5 }} />
                  {STATUS.map((s, i) => (
                    <Bar
                      key={s.key}
                      dataKey={s.key}
                      name={s.label}
                      stackId="status"
                      fill={s.paint}
                      hide={hidden.has(s.key)}
                      stroke="var(--surface-1)"
                      strokeWidth={1}
                      radius={i === STATUS.length - 1 ? [4, 4, 0, 0] : undefined}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </figure>
            <DataTableDisclosure name={`results per ${unit}`}>
              <table className="data">
                <thead>
                  <tr><th>{unit === "day" ? "Date" : unit === "week" ? "Week of" : "Month"}</th><th className="num">Runs</th><th className="num">Passed</th><th className="num">Failed</th><th className="num">Errored</th><th className="num">Skipped</th></tr>
                </thead>
                <tbody>
                  {trendDays.map((d) => (
                    <tr key={d.date}>
                      <td>{d.date}</td><td className="num">{d.runs}</td><td className="num">{d.passed}</td><td className="num">{d.failed}</td><td className="num">{d.errored}</td><td className="num">{d.skipped}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableDisclosure>
          </div>

          <div className="card">
            <h2 id="trend-rate">Pass rate per {unit}</h2>
            <PassRateChart buckets={trendDays} bucket={bucket} height={180} narrow={narrow} labelledBy="trend-rate" />
            <DataTableDisclosure name={`pass rate per ${unit}`}>
              <table className="data">
                <thead>
                  <tr><th>{unit === "day" ? "Date" : unit === "week" ? "Week of" : "Month"}</th><th className="num">Pass rate</th><th className="num">Avg duration</th></tr>
                </thead>
                <tbody>
                  {trendDays.map((d) => (
                    <tr key={d.date}>
                      <td>{d.date}</td><td className="num">{formatPassRate(d.pass_rate)}</td><td className="num">{formatDuration(d.avg_run_duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableDisclosure>
          </div>
        </>
      )}

    </section>
  );
}
