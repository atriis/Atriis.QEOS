import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type TrendBucket, type TrendDay, formatPassRate } from "../api/analytics";
import { AXIS_TICK, TOOLTIP_STYLES, formatPointLabel, formatTick } from "../lib/chartFormat";

/** The off-screen caption: first and last rated bucket, and the lowest one. */
export function passRateSummary(buckets: TrendDay[], bucket: TrendBucket): string {
  const rated = buckets.filter((d) => d.pass_rate !== null);
  if (rated.length === 0) return `Pass rate per ${bucket}: no ${bucket} had counted results.`;
  const lowest = rated.reduce((w, d) => ((d.pass_rate as number) < (w.pass_rate as number) ? d : w));
  return `Pass rate per ${bucket}, from ${formatPassRate(rated[0].pass_rate)} to ${formatPassRate(rated[rated.length - 1].pass_rate)}; `
    + `lowest ${formatPassRate(lowest.pass_rate)} on ${formatPointLabel(lowest.date, bucket)}.`;
}

interface Props {
  buckets: TrendDay[];
  bucket: TrendBucket;
  height: number;
  /** Narrow screens thin the ticks and the axis. */
  narrow?: boolean;
  /** The heading that names the figure. */
  labelledBy?: string;
}

/** The pass rate per bucket as a line with markers (a gap where a bucket had no counted results), with its summary as
 *  an off-screen caption. The Trends view and the Overview's Pass-rate trend draw the same chart. */
export default function PassRateChart({ buckets, bucket, height, narrow = false, labelledBy }: Props) {
  const points = buckets.map((d) => ({ date: d.date, ratePct: d.pass_rate === null ? null : d.pass_rate * 100 }));
  return (
    <figure className="chart-figure" aria-labelledby={labelledBy}>
      <figcaption className="sr-only">{passRateSummary(buckets, bucket)}</figcaption>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={points} accessibilityLayer>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="date" stroke="var(--text-muted)" tick={AXIS_TICK} tickLine={false} tickFormatter={(v: string) => formatTick(v, bucket)} minTickGap={narrow ? 36 : 16} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} stroke="var(--text-muted)" tick={AXIS_TICK} tickLine={false} width={narrow ? 40 : 48} />
          <Tooltip
            {...TOOLTIP_STYLES}
            labelFormatter={(v) => formatPointLabel(String(v), bucket)}
            cursor={{ stroke: "var(--grid)" }}
            formatter={(v) => [`${Number(v).toFixed(1)}%`, "Pass rate"]}
          />
          <Line dataKey="ratePct" stroke="var(--accent)" strokeWidth={2} dot={{ r: 2.5, fill: "var(--accent)", stroke: "var(--surface-1)" }} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}
