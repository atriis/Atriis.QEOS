import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { formatDuration, formatPassRate, getTests } from "../api/analytics";
import { downloadCsv, toCsv } from "../lib/csv";
import { fetchAllTests } from "../lib/exportData";
import ErrorBanner from "../components/ErrorBanner";
import NarrowMeta from "../components/NarrowMeta";
import FilterBar from "../components/FilterBar";
import FilterChips from "../components/FilterChips";
import SortableTh from "../components/SortableTh";
import StatusDot from "../components/StatusDot";
import { nextSort, parseSort, sortPatch, sortRows, SortState } from "../lib/sort";
import { oneOf, useDraft, useUrlState } from "../lib/useUrlState";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const PAGE = 50;
const DEFAULTS = { days: "30", sort: "failed", dir: "", search: "" } as const;
const DAYS = ["7", "30", "90"] as const;
// The API orders pages by failures, duration or name (its own direction); the other columns, and the
// opposite direction, reorder the rows that are loaded.
const SORT_KEYS = ["name", "failed", "rate", "duration", "seen"] as const;
type SortKey = (typeof SORT_KEYS)[number];
const SERVER_SORT = { name: "name", failed: "failures", duration: "duration" } as const;
const DEFAULT_SORT: SortState<SortKey> = { key: "failed", dir: "desc" };

export default function TestsPage() {
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const { projectId } = useParams();
  const id = Number(projectId);
  const { values, offset, update, setOffset } = useUrlState(DEFAULTS, PAGE);
  const days = Number(oneOf(values.days, DAYS, "30"));
  const sort = parseSort(values.sort === "failures" ? "failed" : values.sort, values.dir || (values.sort === "name" ? "asc" : "desc"), SORT_KEYS, DEFAULT_SORT);
  const serverSort = sort.key in SERVER_SORT ? SERVER_SORT[sort.key as keyof typeof SERVER_SORT] : "failures";
  const onSort = (key: SortKey) => {
    const next = nextSort(sort, key, key === "name" ? "asc" : "desc");
    update(sortPatch(next, DEFAULT_SORT));
  };
  const search = values.search;
  // The text box is a draft until Apply (per-keystroke requests hit the shared rate limit)
  const [searchInput, setSearchInput, commitSearch] = useDraft(search);

  // One extra row tells whether another page exists, so an exact multiple of the page size ends cleanly
  const query = useQuery({
    queryKey: ["tests", id, days, serverSort, search, offset],
    queryFn: () => getTests(id, { days, sort: serverSort, search: search || undefined, limit: PAGE + 1, offset }),
    placeholderData: keepPreviousData,
  });

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    update({ search: commitSearch((raw) => raw.trim()) });
  }

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);

  async function onExport() {
    setExporting(true);
    setExportError(null);
    try {
      const all = await fetchAllTests(id, { days, sort: serverSort, search: search || undefined });
      const csv = toCsv(
        ["test_key", "suite", "class_name", "name", "runs", "passed", "failed", "errored",
         "skipped", "pass_rate", "avg_duration_ms", "last_status", "last_seen"],
        all.map((r) => [r.test_key, r.suite, r.class_name, r.name, r.runs, r.passed, r.failed,
          r.errored, r.skipped, r.pass_rate, r.avg_duration_ms, r.last_status, r.last_seen]),
      );
      downloadCsv(`tests-project-${id}-${days}d.csv`, csv);
    } catch (err) {
      setExportError(err);
    } finally {
      setExporting(false);
    }
  }

  const fetched = query.data ?? [];
  const rows = sortRows(fetched.slice(0, PAGE), sort, (r, key) =>
    key === "name" ? r.name : key === "failed" ? r.failed : key === "rate" ? r.pass_rate : key === "duration" ? r.avg_duration_ms : Date.parse(r.last_seen));
  const hasMore = fetched.length > PAGE;

  return (
    <section>
      <PageHeader title="Test results" />
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
            Search
            <input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
          </label>
          <button type="submit">Apply</button>
          <button type="button" onClick={onExport} disabled={exporting}>
            {exporting ? "Exporting…" : "Export CSV"}
          </button>
        </FilterBar>
      </form>
      {/* No outcome filter here: the chips row only lists what is applied */}
      <FilterChips values={values}
        applied={[
          ...(values.days !== DEFAULTS.days ? [{ key: "days", name: "Days", value: String(days) }] : []),
          ...(search ? [{ key: "search", name: "Search", value: search }] : []),
        ]}
        onChange={update} onClearAll={() => {
          // Clear all means a blank form, the unapplied Search draft included
          setSearchInput("");
          update({ days: "", search: "" });
        }} />

      {exportError != null && <ErrorBanner error={exportError} onRetry={onExport} />}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {query.isPending && <p className="muted">Loading tests…</p>}
      {query.data && rows.length === 0 && (
        <p className="muted">
          {offset > 0 ? "No tests on this page." : search ? `No tests match "${search}" in the last ${days} days.` : `No tests in the last ${days} days.`}
        </p>
      )}
      {query.data && rows.length === 0 && offset > 0 && (
        <div className="pager">
          <button onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
        </div>
      )}

      {rows.length > 0 && (
        <div ref={card.ref} className={tableCardClass(card.wide)} tabIndex={0} role="region" aria-label="Test results">
          <table className="data">
            <thead>
              <tr>
                <SortableTh label="Test" sortKey="name" sort={sort} onSort={onSort} />
                <th className="hide-narrow num">Runs</th>
                <SortableTh label="Pass rate" sortKey="rate" sort={sort} onSort={onSort} className="num" />
                <SortableTh label="Failed" sortKey="failed" sort={sort} onSort={onSort} className="num" />
                <th className="hide-narrow num">Errored</th>
                <SortableTh label="Avg duration" sortKey="duration" sort={sort} onSort={onSort} className="hide-narrow num" />
                <th>Last status</th>
                <SortableTh label="Last seen" sortKey="seen" sort={sort} onSort={onSort} className="hide-narrow" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.test_key}>
                  <td>
                    <Link to={`../tests/${encodeURIComponent(r.test_key)}`} relative="path">
                      {r.name}
                    </Link>
                    <div className="muted">{r.suite} / {r.class_name}</div>
                    <NarrowMeta items={[
                      { label: "Runs", value: r.runs },
                      { label: "Errored", value: r.errored },
                      { label: "Avg duration", value: formatDuration(r.avg_duration_ms) },
                      { label: "Last seen", value: new Date(r.last_seen).toLocaleString() },
                    ]} />
                  </td>
                  <td className="hide-narrow num">{r.runs}</td>
                  <td className="num">{formatPassRate(r.pass_rate)}</td>
                  <td className="num">{r.failed}</td>
                  <td className="hide-narrow num">{r.errored}</td>
                  <td className="hide-narrow num">{formatDuration(r.avg_duration_ms)}</td>
                  <td><StatusDot status={r.last_status} /></td>
                  <td className="hide-narrow">{new Date(r.last_seen).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!(sort.key in SERVER_SORT) && (
            <p className="muted live-note">Sorted within these {rows.length} rows; the pages follow failures.</p>
          )}
          <div className="pager">
            <span className="muted">Rows {offset + 1}–{offset + rows.length}</span>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </button>
            <button disabled={!hasMore} onClick={() => setOffset(offset + PAGE)}>
              Next
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
