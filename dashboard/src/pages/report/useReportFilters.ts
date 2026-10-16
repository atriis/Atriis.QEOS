import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CI_LABELS } from "../../lib/ciProviders";
import {
  MAX_AGE_DAYS, MAX_SPAN_DAYS, PRESETS, type Preset, addDays, isDay, spanDays, todayIn,
} from "../../lib/period";
import { type AreaFilter, parseArea } from "../../lib/reportScope";

/** The report's filters live in the URL (spec: Filters): reload, share and Back restore them. The period helpers
 *  are shared with the Test cases list (lib/period) and re-exported here for the report's own modules. */
export { MAX_AGE_DAYS, MAX_SPAN_DAYS, PRESETS, type Preset, addDays, spanDays, todayIn };

export const DEFAULT_PRESET: Preset = "30";
/** `branch=*`: every branch. No `branch`: the project's default branch (plan Ruling 1). `*` is not a legal git branch name. */
export const ALL_BRANCHES = "*";

export const FILTER_KEYS = ["period", "from", "to", "branch", "env", "ci", "origin", "area", "suite"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
const PERIOD_KEYS: readonly FilterKey[] = ["period", "from", "to"];

export interface ReportFilters {
  /** null: a custom from-to range */
  preset: Preset | null;
  from: string;
  to: string;
  days: number;
  /** "" = the project's default branch; ALL_BRANCHES = every branch; else that branch */
  branch: string;
  environment: string;
  ci: string;
  origin: "any" | "ci" | "qeos";
  area: AreaFilter | null;
  suite: number | null;
}

const noNul = (s: string) => !s.includes("\u0000");

/** Reads and checks the URL. Invalid parameters are listed in `dropped` and read as unset. */
export function parseReportFilters(params: URLSearchParams, today: string): { filters: ReportFilters; dropped: FilterKey[] } {
  const dropped: FilterKey[] = [];
  const get = (k: FilterKey) => params.get(k) ?? "";

  let preset: Preset | null = DEFAULT_PRESET;
  const period = get("period");
  if (period && !(PRESETS as readonly string[]).includes(period)) dropped.push("period");
  else if (period) preset = period as Preset;

  let from = "";
  let to = "";
  const rawFrom = get("from");
  const rawTo = get("to");
  if (rawFrom || rawTo) {
    const ok = isDay(rawFrom) && isDay(rawTo) && rawFrom <= rawTo && spanDays(rawFrom, rawTo) <= MAX_SPAN_DAYS
      && rawTo <= today && rawFrom >= addDays(today, -MAX_AGE_DAYS);
    if (ok) {
      from = rawFrom;
      to = rawTo;
      preset = null;
    } else {
      if (rawFrom) dropped.push("from");
      if (rawTo) dropped.push("to");
    }
  }
  if (preset !== null) {
    to = today;
    from = addDays(today, -(Number(preset) - 1));
  }

  const branch = get("branch");
  const okBranch = branch.length <= 255 && noNul(branch);
  if (!okBranch) dropped.push("branch");
  const env = get("env");
  const okEnv = env.length <= 100 && noNul(env);
  if (!okEnv) dropped.push("env");
  const ci = get("ci");
  const okCi = ci === "" || Object.hasOwn(CI_LABELS, ci);
  if (!okCi) dropped.push("ci");
  const origin = get("origin");
  const okOrigin = origin === "" || origin === "ci" || origin === "qeos";
  if (!okOrigin) dropped.push("origin");
  const rawArea = get("area");
  const area = rawArea ? parseArea(rawArea) : null;
  if (rawArea && !area) dropped.push("area");
  const rawSuite = get("suite");
  const okSuite = rawSuite === "" || /^[1-9]\d{0,9}$/.test(rawSuite);
  if (!okSuite) dropped.push("suite");

  return {
    filters: {
      preset, from, to, days: spanDays(from, to),
      branch: okBranch ? branch : "",
      environment: okEnv ? env : "",
      ci: okCi ? ci : "",
      origin: okOrigin && origin ? (origin as "ci" | "qeos") : "any",
      area,
      suite: okSuite && rawSuite ? Number(rawSuite) : null,
    },
    dropped,
  };
}

export function useReportFilters(tz: string) {
  const [params, setParams] = useSearchParams();
  const today = todayIn(tz);
  const { filters, dropped } = useMemo(() => parseReportFilters(params, today), [params, today]);

  // A hand-edited or stale link: remove what is invalid (replacing the history entry, so Back does not
  // return to it) and say so until dismissed
  const [notice, setNotice] = useState(false);
  const droppedKey = dropped.join("|");
  useEffect(() => {
    if (!droppedKey) return;
    setNotice(true);
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const key of droppedKey.split("|")) next.delete(key);
      return next;
    }, { replace: true });
  }, [droppedKey, setParams]);

  /** "" removes a key. A preset removes the custom range and the other way round; the default preset is left out. */
  const update = useCallback((patch: Partial<Record<FilterKey, string>>) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [key, value] of Object.entries(patch)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      if (patch.period) {
        next.delete("from");
        next.delete("to");
      }
      if (patch.from || patch.to) next.delete("period");
      if (next.get("period") === DEFAULT_PRESET) next.delete("period");
      return next;
    });
  }, [setParams]);

  /** Every filter back to its default except the period; view settings (P3 grouping) stay. */
  const clearAll = useCallback(() => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const key of FILTER_KEYS) if (!PERIOD_KEYS.includes(key)) next.delete(key);
      return next;
    });
  }, [setParams]);

  const dismissNotice = useCallback(() => setNotice(false), []);
  return { filters, update, clearAll, notice, dismissNotice };
}
