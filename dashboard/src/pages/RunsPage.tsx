import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { listRuns, RunFilters, RunScope, SCOPES } from "../api/runs";
import { listLogPatterns } from "../api/logPatterns";
import { RUNS_PAGE_SIZE } from "../lib/runQueries";
import { formatDuration, getBranches } from "../api/analytics";
import ErrorBanner from "../components/ErrorBanner";
import FilterBar from "../components/FilterBar";
import FilterChips, { revealFilters, type AppliedFilter, type QuickChip } from "../components/FilterChips";
import FilterSelect from "../components/FilterSelect";
import NarrowMeta from "../components/NarrowMeta";
import { runVerdict } from "../components/RunStatusBadge";
import StatusPill, { RunVerdictPill } from "../components/StatusPill";
import SortableTh from "../components/SortableTh";
import { nextSort, parseSort, sortRows, SortState } from "../lib/sort";
import { LIVE_REFRESH_MS } from "../lib/live";
import { pageOffset, withOffset } from "../lib/useUrlState";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";
import { CI_LABELS } from "../lib/ciProviders";
import { isSubset, stoppedAfterStage1 } from "../lib/runScope";

// Shared with the Overview's run widgets, so their first page is this view's answer
const PAGE = RUNS_PAGE_SIZE;
// The branch list's reach: the API's longest period and largest page
const BRANCH_DAYS = 365;
const BRANCH_LIMIT = 200;
// The API has no sort parameter for runs: the columns sort the page that is loaded
const SORT_KEYS = ["started", "duration", "failed"] as const;
type SortKey = (typeof SORT_KEYS)[number];
const DEFAULT_SORT: SortState<SortKey> = { key: "started", dir: "desc" };

// URL keys, in URL order. "from" and "to" are local calendar days
// (YYYY-MM-DD); the rest go to the API unchanged.
const KEYS = ["status", "branch", "environment", "ci_provider", "commit", "pr", "author", "scope", "from", "to", "value", "pattern"] as const;
const ADVANCED = ["environment", "ci_provider", "commit", "pr", "author", "scope", "from", "to", "value", "pattern"] as const;
type Key = (typeof KEYS)[number];
type Values = Record<Key, string>;

/** run-impact's partial runs (spec 2026-10-13 §3.2): "full" hides them. */
const SCOPE_LABELS: Record<RunScope, string> = { full: "Full runs only", "impact-subset": "Suggested tests only" };
const asScope = (s: string): RunScope | undefined => SCOPES.find((scope) => scope === s);

const QUICK: QuickChip[] = [
  { key: "status", value: "failing", label: "Failed" },
  { key: "status", value: "passing", label: "Passed" },
  { key: "branch", value: "main", label: "main" },
  { key: "scope", value: "full", label: "Full runs only" },
];
const FILTER_NAMES: Record<Key, string> = {
  status: "Status", branch: "Branch", environment: "Environment", ci_provider: "CI", commit: "Commit",
  pr: "Pull request", author: "Author", scope: "Runs", from: "From", to: "To", value: "Log value", pattern: "Pattern",
};
function appliedFilters(v: Values): AppliedFilter[] {
  // The log value and its pattern are one filter ("Log value trip_id: 3960562"); removing it drops both keys
  return KEYS.filter((k) => v[k] !== "" && k !== "pattern").map((k) => {
    const scope = k === "scope" ? asScope(v[k]) : undefined;
    return {
      key: k,
      name: k === "value" && v.pattern ? `Log value ${v.pattern}` : FILTER_NAMES[k],
      value: k === "status" ? (v[k] === "failing" ? "With failures" : v[k] === "passing" ? "All green" : v[k])
        : k === "ci_provider" ? CI_LABELS[v[k]] ?? v[k] : k === "pr" ? `#${v[k]}`
        : scope ? SCOPE_LABELS[scope] : v[k],
    };
  });
}

function readValues(params: URLSearchParams): Values {
  return Object.fromEntries(KEYS.map((k) => [k, params.get(k) ?? ""])) as Values;
}

/** The instant a local calendar day starts, as a UTC ISO string. */
function dayStart(day: string, plusDays = 0): string | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) return undefined;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + plusDays).toISOString();
}

function toFilters(v: Values): RunFilters {
  return {
    status: v.status === "failing" || v.status === "passing" ? v.status : undefined,
    branch: v.branch || undefined,
    environment: v.environment || undefined,
    ci_provider: v.ci_provider || undefined,
    commit: v.commit || undefined,
    pr: v.pr ? Number(v.pr) : undefined,
    author: v.author || undefined,
    scope: asScope(v.scope),
    value: v.value || undefined,
    pattern: v.value ? v.pattern || undefined : undefined,
    since: dayStart(v.from),
    // People read "to" as inclusive, so the API gets the start of the next day
    until: dayStart(v.to, 1),
  };
}

export default function RunsPage() {
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const { projectId } = useParams();
  const id = Number(projectId);
  const [params, setParams] = useSearchParams();
  const filterSearch = withOffset(params, 0).toString();
  const offset = pageOffset(params, PAGE);
  const setOffset = (to: number) => setParams((prev) => withOffset(prev, to));
  const applied = readValues(params);
  const filters = toFilters(applied);
  const sort = parseSort(params.get("sort"), params.get("dir"), SORT_KEYS, DEFAULT_SORT);
  function onSort(key: SortKey) {
    const next = nextSort(sort, key, "desc");
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next.key === DEFAULT_SORT.key && next.dir === DEFAULT_SORT.dir) {
        p.delete("sort");
        p.delete("dir");
      } else {
        p.set("sort", next.key);
        p.set("dir", next.dir);
      }
      return p;
    });
  }
  const active = KEYS.filter((k) => applied[k] !== "").length;
  const advancedActive = ADVANCED.filter((k) => applied[k] !== "").length;
  const [form, setForm] = useState<Values>(applied);

  // A pasted link or back/forward changes the URL: the form follows it
  useEffect(() => {
    setForm(readValues(new URLSearchParams(filterSearch)));
  }, [filterSearch]);

  const query = useQuery({
    queryKey: ["runs", id, filters, offset],
    queryFn: () => listRuns(id, { limit: PAGE, offset, ...filters }),
    placeholderData: keepPreviousData,
    // Only the first page follows new uploads; later pages would shift under the reader
    refetchInterval: offset === 0 ? LIVE_REFRESH_MS : false,
  });

  // Runs that arrived since the first page was last shown, announced once
  const newest = useRef<{ view: string; top: number } | null>(null);
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const view = `${id}?${filterSearch}`;
  useEffect(() => {
    const data = query.data;
    if (!data || offset !== 0 || query.isPlaceholderData) return;
    const top = data.length > 0 ? data[0].id : 0;
    const seen = newest.current;
    if (seen && seen.view === view && top > seen.top) {
      setFresh(new Set(data.filter((r) => r.id > seen.top).map((r) => r.id)));
    } else if (!seen || seen.view !== view) {
      setFresh(new Set());
    }
    newest.current = { view, top: Math.max(top, seen?.view === view ? seen.top : 0) };
  }, [query.data, query.isPlaceholderData, offset, view]);

  // A filter change is announced once its runs arrive ("12 runs"), in the same status line as new runs
  const filterKey = KEYS.map((k) => applied[k]).join("\u0000");
  const announcedFor = useRef<string | null>(null);
  const [countNote, setCountNote] = useState("");
  useEffect(() => {
    const data = query.data;
    if (!data || query.isPlaceholderData) return;
    if (announcedFor.current !== null && announcedFor.current !== filterKey) {
      const n = data.length;
      setCountNote(n >= PAGE ? `${PAGE}+ runs` : `${n} run${n === 1 ? "" : "s"}`);
    }
    announcedFor.current = filterKey;
  }, [query.data, query.isPlaceholderData, filterKey]);

  function set(key: Key, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const k of KEYS) {
      const value = form[k].trim();
      if (value) next.set(k, value);
    }
    keepSort(next);
    setParams(next);
  }

  /** Filters change which runs load; the chosen order stays */
  function keepSort(next: URLSearchParams) {
    for (const k of ["sort", "dir"]) {
      const v = params.get(k);
      if (v) next.set(k, v);
    }
  }

  // Chips patch the applied URL; the sort stays, the page goes back to 1
  function patchFilters(patch: Record<string, string>) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      if (patch.value === "") next.delete("pattern");
      next.delete("offset");
      return next;
    });
  }
  const moreRef = useRef<HTMLDetailsElement>(null);
  // Controlled, so removing the last advanced filter does not fold it under the reader; a new one opens it
  const [moreOpen, setMoreOpen] = useState(advancedActive > 0);
  // The pattern names for the Log value filter (spec 2026-10-15 §3.2), read once More filters is open or a pattern
  // is already in the URL; a project without patterns offers none
  const patterns = useQuery({
    queryKey: ["log-patterns", id], queryFn: () => listLogPatterns(id), staleTime: 60_000,
    enabled: moreOpen || applied.pattern !== "",
  });
  const patternOptions = (patterns.data?.patterns ?? []).map((p) => ({ value: p.name, label: p.name }));
  // The branch filter is an exact match, so it offers the project's branches: those with runs in the last year, as
  // many as the API lists, A to Z. A branch from the URL that is not among them stays on offer
  const branchList = useQuery({
    queryKey: ["branches", id, BRANCH_DAYS, "all"],
    queryFn: () => getBranches(id, { days: BRANCH_DAYS, limit: BRANCH_LIMIT }),
    staleTime: 60_000,
  });
  const branchNames = new Set((branchList.data ?? []).flatMap((b) => (b.branch === null ? [] : [b.branch])));
  if (form.branch) branchNames.add(form.branch);
  const branchOptions = [...branchNames].sort((a, b) => a.localeCompare(b)).map((b) => ({ value: b, label: b }));
  // While the value filter is on, each run opens scoped to the results holding it
  const runSearch = applied.value
    ? `?${new URLSearchParams({ value: applied.value, ...(applied.pattern ? { pattern: applied.pattern } : {}) })}` : "";
  const hadAdvanced = useRef(advancedActive > 0);
  useEffect(() => {
    if (advancedActive > 0 && !hadAdvanced.current) setMoreOpen(true);
    hadAdvanced.current = advancedActive > 0;
  }, [advancedActive]);

  // Clear all means a blank form, unapplied drafts included
  function clearFilters() {
    setForm(readValues(new URLSearchParams()));
    const next = new URLSearchParams();
    keepSort(next);
    setParams(next);
  }

  const rows = sortRows(query.data ?? [], sort, (r, key) =>
    key === "started" ? Date.parse(r.started_at) : key === "duration" ? r.duration_ms : r.failed);

  return (
    <section>
      <PageHeader title="Runs" tabs={[{ label: "Runs" }, { label: "Requested runs", to: "requested" }]} />
      <form onSubmit={applyFilters}>
        <FilterBar>
          <FilterSelect label="Status" value={form.status} emptyLabel="All" onChange={(v) => set("status", v)}
            options={[{ value: "failing", label: "With failures" }, { value: "passing", label: "All green" }]} />
          <FilterSelect label="Branch" value={form.branch} emptyLabel="All" onChange={(v) => set("branch", v)}
            options={branchOptions} />
          <button type="submit" className="primary">Apply</button>
        </FilterBar>
        <details ref={moreRef} className="more-filters" open={moreOpen}
          onToggle={(e) => setMoreOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary><ChevronRight size={14} aria-hidden="true" className="chevron" /> More filters{advancedActive > 0 && ` (${advancedActive} active)`}</summary>
          <FilterBar>
            <label>
              Environment
              <input value={form.environment} onChange={(e) => set("environment", e.target.value)} maxLength={100} />
            </label>
            <FilterSelect label="CI" value={form.ci_provider} onChange={(v) => set("ci_provider", v)}
              options={Object.entries(CI_LABELS).map(([value, label]) => ({ value, label }))} />
            <label>
              Commit
              <input
                value={form.commit}
                onChange={(e) => set("commit", e.target.value)}
                pattern="[0-9a-fA-F]{4,40}"
                title="At least 4 characters of the commit hash"
                spellCheck={false}
                autoComplete="off"
              />
            </label>
            <label>
              Pull request
              <input type="number" min={1} inputMode="numeric" value={form.pr} onChange={(e) => set("pr", e.target.value)} />
            </label>
            <label>
              Author
              <input value={form.author} onChange={(e) => set("author", e.target.value)} maxLength={255} />
            </label>
            <FilterSelect label="Runs" value={form.scope} emptyLabel="All" onChange={(v) => set("scope", v)}
              options={SCOPES.map((value) => ({ value, label: SCOPE_LABELS[value] }))} />
            <label>
              From
              <input type="date" value={form.from} max={form.to || undefined} onChange={(e) => set("from", e.target.value)} />
            </label>
            <label>
              To
              <input type="date" value={form.to} min={form.from || undefined} onChange={(e) => set("to", e.target.value)} />
            </label>
            <label>
              Log value
              <input value={form.value} onChange={(e) => set("value", e.target.value)} maxLength={200}
                spellCheck={false} autoComplete="off" placeholder="3960562" />
            </label>
            {patternOptions.length > 0 && (
              <FilterSelect label="Pattern" value={form.pattern} emptyLabel="Any pattern" onChange={(v) => set("pattern", v)}
                options={patternOptions} />
            )}
          </FilterBar>
        </details>
      </form>
      <FilterChips quick={QUICK} values={applied} applied={appliedFilters(applied)} onChange={patchFilters}
        onClearAll={clearFilters} onAddFilter={() => revealFilters(moreRef.current)} />

      <p role="status" className="muted live-note">
        {fresh.size > 0 ? `${fresh.size} new run${fresh.size === 1 ? "" : "s"}` : countNote}
      </p>
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {query.isPending && <p className="muted">Loading runs…</p>}
      {query.data && rows.length === 0 && (
        offset > 0 ? (
          <p className="muted">No runs on this page.</p>
        ) : active > 0 ? (
          <p className="muted">No runs match these filters.</p>
        ) : (
          <p className="muted">No runs yet.</p>
        )
      )}
      {query.data && rows.length === 0 && offset > 0 && (
        <div className="pager">
          <button onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
        </div>
      )}

      {rows.length > 0 && (
        <div ref={card.ref} className={tableCardClass(card.wide)} tabIndex={0} role="region" aria-label="Runs">
          <table className="data">
            <thead>
              <tr>
                <th>Run</th><th className="hide-narrow">Status</th>
                <SortableTh label="Started" sortKey="started" sort={sort} onSort={onSort} />
                <th>Branch</th><th className="hide-narrow">Commit</th><th className="hide-narrow">Environment</th>
                <th className="hide-narrow">CI</th><th className="num">Passed</th><SortableTh label="Failed" sortKey="failed" sort={sort} onSort={onSort} className="num" /><th className="hide-narrow num">Errored</th><th className="hide-narrow num">Skipped</th><SortableTh label="Duration" sortKey="duration" sort={sort} onSort={onSort} className="hide-narrow num" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={fresh.has(r.id) ? "row-new" : undefined}>
                  <td>
                    <Link to={`${r.id}${runSearch}`}>#{r.id}</Link>
                    {isSubset(r) && (
                      <>{" "}<StatusPill tone="neutral" label="Suggested only"
                        note={stoppedAfterStage1(r) ? "stopped after stage 1" : undefined} /></>
                    )}
                    <NarrowMeta items={[
                      { label: "Status", value: <RunVerdictPill verdict={runVerdict(r)} /> },
                      { label: "Commit", value: r.commit_sha ? r.commit_sha.slice(0, 7) : "—" },
                      { label: "Environment", value: r.environment ?? "—" },
                      { label: "CI", value: CI_LABELS[r.ci_provider] ?? r.ci_provider },
                      { label: "Errored", value: r.errored },
                      { label: "Skipped", value: r.skipped },
                      { label: "Duration", value: formatDuration(r.duration_ms) },
                    ]} />
                  </td>
                  <td className="hide-narrow"><RunVerdictPill verdict={runVerdict(r)} /></td>
                  <td>{new Date(r.started_at).toLocaleString()}</td>
                  <td>{r.branch ?? "—"}</td>
                  <td className="hide-narrow">{r.commit_sha ? r.commit_sha.slice(0, 7) : "—"}</td>
                  <td className="hide-narrow">{r.environment ?? "—"}</td>
                  <td className="hide-narrow">
                    {r.ci_run_url ? (
                      <a href={r.ci_run_url} target="_blank" rel="noreferrer">
                        {CI_LABELS[r.ci_provider] ?? r.ci_provider}
                      </a>
                    ) : (
                      CI_LABELS[r.ci_provider] ?? r.ci_provider
                    )}
                  </td>
                  <td className="num">{r.passed}</td>
                  <td className="num">{r.failed}</td>
                  <td className="hide-narrow num">{r.errored}</td>
                  <td className="hide-narrow num">{r.skipped}</td>
                  <td className="hide-narrow num">{formatDuration(r.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <span className="muted">Rows {offset + 1}–{offset + rows.length}</span>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </button>
            <button disabled={rows.length < PAGE} onClick={() => setOffset(offset + PAGE)}>
              Next
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
