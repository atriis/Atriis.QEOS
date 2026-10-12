import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crosshair, Plus, Upload } from "lucide-react";
import {
  CaseStatus, MAX_SEARCH_KEYS, PRIORITIES, Priority, SEARCH_IN, type SearchIn, listCases, listFeatureGroups, listFeatures,
  listFolders, listLabels,
} from "../api/cases";
import { CASES_PAGE, caseSearchQuery, latestKeysQuery } from "../lib/caseQueries";
import { FEATURES_PAGE, GROUP_CASES_MAX, groupByFeature } from "../lib/featureQueries";
import { MAX_RUN_CASES } from "../api/runRequests";
import CaseTable, { type CaseRowData } from "../components/CaseTable";
import CasesKpis from "../components/CasesKpis";
import ErrorBanner from "../components/ErrorBanner";
import FilterBar from "../components/FilterBar";
import FilterChips, { revealFilters, type AppliedFilter, type QuickChip } from "../components/FilterChips";
import FiltersDisclosure from "../components/FiltersDisclosure";
import FilterSelect from "../components/FilterSelect";
import FolderSelect from "../components/FolderSelect";
import FeatureList from "../components/FeatureList";
import LikelyAffectedPanel from "../components/LikelyAffectedPanel";
import RunControl from "../components/RunControl";
import RunPanel from "../components/RunPanel";
import { useCanEdit } from "../lib/useCanEdit";
import { useFocusReturn } from "../lib/useFocusReturn";
import { ESTIMATE_DEBOUNCE_MS, approxDuration, useDurationEstimate } from "../lib/durationEstimate";
import { useStickyBottomOffset } from "../lib/useStickyOffset";
import { pageOffset, withOffset } from "../lib/useUrlState";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const RESULTS = ["passed", "failed", "skipped", "never"];
const LEGEND = [["passed", "Passed"], ["failed", "Failed"], ["rerun", "Re-run"], ["skipped", "Skipped"], ["none", "Didn't run"]] as const;
const KEYS = ["q", "label", "status", "priority", "origin", "folder", "linked", "result", "feature", "ado"] as const;
// The form also holds where the search looks; it is part of the search, not a filter of its own (no chip)
const FORM_KEYS = [...KEYS, "search_in"] as const;
type Values = Record<(typeof FORM_KEYS)[number], string>;
// Filters GET /features cannot apply: with one of these the Feature view groups the matching cases itself
const CASE_ONLY = ["result", "origin", "feature", "ado"] as const;
type Group = "feature" | "scenario";
const LIKELY_AFFECTED_ID = "likely-affected";
const SEARCH_IN_NAMES: Record<SearchIn, string> = { feature: "Feature", scenario: "Scenario", both: "Both" };
const SEARCH_HINT: Record<SearchIn, string> = { feature: "feature name or path", scenario: "title, steps or TC key", both: "feature or scenario" };

// One press each; chips that share a key are one choice
const QUICK: QuickChip[] = [
  { key: "result", value: "failed", label: "Failing" },
  { key: "result", value: "never", label: "Never ran" },
  { key: "linked", value: "true", label: "Linked" },
  { key: "linked", value: "false", label: "Manual" },
  { key: "status", value: "draft", label: "Draft" },
  { key: "status", value: "ready", label: "Ready" },
];
// How an applied filter reads in its chip
const FILTER_NAMES: Record<(typeof KEYS)[number], string> = {
  q: "Search", label: "Label", status: "Status", priority: "Priority", origin: "Origin", folder: "Folder",
  linked: "Link", result: "Latest result", feature: "Feature", ado: "Azure DevOps",
};
const VALUE_NAMES: Partial<Record<(typeof KEYS)[number], Record<string, string>>> = {
  status: { draft: "Draft", ready: "Ready", archived: "Archived" },
  origin: { manual: "Manual", imported: "Imported" },
  linked: { true: "Linked", false: "Not linked" },
  result: { passed: "Passed", failed: "Failed", skipped: "Skipped", never: "Never ran" },
};
function appliedFilters(v: Values): AppliedFilter[] {
  // A search chip reads where it looks, when the reader chose
  return KEYS.filter((k) => v[k] !== "").map((k) => ({
    key: k,
    name: k === "q" && SEARCH_IN.includes(v.search_in as SearchIn) ? `Search (${SEARCH_IN_NAMES[v.search_in as SearchIn].toLowerCase()})` : FILTER_NAMES[k],
    value: k === "folder" ? v[k].split("/").join(" / ") : k === "ado" ? `#${v[k]}` : VALUE_NAMES[k]?.[v[k]] ?? v[k],
  }));
}

const read = (p: URLSearchParams): Values =>
  Object.fromEntries(FORM_KEYS.map((k) => [k, p.get(k) ?? ""])) as Values;

/** A selected case: what the Play dialog lists, and the test it runs (for the duration estimate). */
interface Picked { title: string; testKey: string | null }

/** The project's written test cases: search, filter, open, write a new one; grouped by .feature file or listed. */
export default function CasesPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const canEdit = useCanEdit(id);
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const applied = read(params);
  const [form, setForm] = useState<Values>(applied);
  const group: Group = params.get("group") === "scenario" ? "scenario" : "feature";
  // Where the search looks: the reader's choice, else the view's own field (feature names, or scenarios)
  const searchIn: SearchIn = SEARCH_IN.includes(applied.search_in as SearchIn) ? (applied.search_in as SearchIn) : group;
  const formSearchIn: SearchIn = SEARCH_IN.includes(form.search_in as SearchIn) ? (form.search_in as SearchIn) : group;
  const offset = pageOffset(params, group === "feature" ? FEATURES_PAGE : CASES_PAGE);
  const setOffset = (to: number) => setParams((prev) => withOffset(prev, to));
  const tableRef = useRef<HTMLDivElement | null>(null);
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const setCard = card.ref;
  const cardRef = useCallback((node: HTMLDivElement | null) => {
    tableRef.current = node;
    setCard(node);
  }, [setCard]);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [picked, setPicked] = useState<Map<number, Picked>>(new Map());
  // Run likely affected: an inline panel that replaces the selection; closing it puts focus back on its button
  const [impactOpen, setImpactOpen] = useState(false);
  const impactButtonRef = useFocusReturn<HTMLButtonElement>(impactOpen);
  const barRef = useRef<HTMLDivElement>(null);
  // The bar sticks to the viewport bottom: rows reached by keyboard must stay above it
  const barHeight = useStickyBottomOffset(barRef, picked.size > 0);
  function toggle(c: CaseRowData) {
    setPicked((now) => {
      const next = new Map(now);
      if (next.has(c.number)) next.delete(c.number);
      else if (next.size < MAX_RUN_CASES) next.set(c.number, { title: c.title, testKey: c.automated_test_key });
      return next;
    });
  }
  function toggleAll(on: boolean, rows: CaseRowData[]) {
    setPicked((now) => {
      const next = new Map(now);
      for (const c of rows) {
        if (!on) next.delete(c.number);
        else if (next.size < MAX_RUN_CASES) next.set(c.number, { title: c.title, testKey: c.automated_test_key });
      }
      return next;
    });
  }
  // The bar's live total: asked 400 ms after the selection settles, the last answer kept meanwhile
  const pickedKeys = useMemo(() => [...picked.values()].map((p) => p.testKey), [picked]);
  const selectionEstimate = useDurationEstimate(id, pickedKeys, { debounceMs: ESTIMATE_DEBOUNCE_MS });
  const search = params.toString();
  const lastApplied = useRef(applied);
  useEffect(() => {
    const next = read(new URLSearchParams(search));
    const before = lastApplied.current;
    lastApplied.current = next;
    setForm((f) => Object.fromEntries(FORM_KEYS.map((k) => [k, next[k] !== before[k] ? next[k] : f[k]])) as Values);
  }, [search]);

  const archived = applied.status === "archived";
  const status = applied.status === "draft" || applied.status === "ready" || archived ? (applied.status as CaseStatus) : undefined;
  const priority = (PRIORITIES as string[]).includes(applied.priority) ? (applied.priority as Priority) : undefined;
  const linked = applied.linked === "true" || applied.linked === "false" ? applied.linked : undefined;
  // The Feature view asks GET /features, unless a filter only the case list knows is in force (or archived cases)
  const grouped = group === "feature" && !archived && CASE_ONLY.every((k) => applied[k] === "");
  const listed = !grouped;
  // Grouping in the page reads one large page of cases
  const caseLimit = group === "scenario" ? CASES_PAGE : GROUP_CASES_MAX;
  const caseOffset = group === "scenario" ? offset : 0;
  const query = useQuery({
    queryKey: ["cases", id, search, caseOffset, caseLimit],
    enabled: listed,
    queryFn: async () => {
      const base = {
        search: applied.q || undefined, search_in: applied.q ? searchIn : undefined, status, priority,
        origin: (applied.origin === "manual" || applied.origin === "imported" ? applied.origin : undefined) as "manual" | "imported" | undefined,
        folder: applied.folder || undefined, feature: applied.feature || undefined, ado: applied.ado || undefined,
        limit: caseLimit, offset: caseOffset,
      };
      const plain = { ...base, label: applied.label || undefined, linked: linked as "true" | "false" | undefined };
      const result = RESULTS.includes(applied.result) ? applied.result : "";
      if (!result) return { page: await listCases(id, plain), notice: null };
      let keys: string[];
      try {
        // Shared with the Failing tile (one request, re-asked at most once a minute)
        keys = (await queryClient.fetchQuery(
          latestKeysQuery(id, result === "never" ? "any" : (result as "passed" | "failed" | "skipped")),
        )).keys;
      } catch {
        return { page: await listCases(id, plain), notice: "unavailable" as const };
      }
      if (keys.length > MAX_SEARCH_KEYS) return { page: await listCases(id, plain), notice: "too-many" as const };
      try {
        return {
          // Keyed by its body: with only Failing applied this is the Failing tile's own search
          page: await queryClient.fetchQuery(caseSearchQuery(id, {
            ...base, labels: applied.label ? [applied.label] : [], linked: linked ? linked === "true" : undefined,
            test_keys: keys, keys_mode: result === "never" ? "exclude" : "include",
          })),
          notice: null,
        };
      } catch {
        return { page: await listCases(id, plain), notice: "unavailable" as const };
      }
    },
    placeholderData: keepPreviousData,
  });
  const featureFilters = {
    search: applied.q || undefined, search_in: searchIn, folder: applied.folder || undefined, label: applied.label || undefined,
    status: status === "draft" || status === "ready" ? status : undefined, priority, linked: linked as "true" | "false" | undefined,
  };
  const features = useQuery({
    queryKey: ["features", id, search, offset],
    enabled: grouped,
    queryFn: () => listFeatureGroups(id, { ...featureFilters, limit: FEATURES_PAGE, offset }),
    placeholderData: keepPreviousData,
  });
  const labels = useQuery({ queryKey: ["case-labels", id], queryFn: () => listLabels(id) });
  const featureNames = useQuery({ queryKey: ["case-features", id], queryFn: () => listFeatures(id) });
  const folders = useQuery({ queryKey: ["case-folders", id], queryFn: () => listFolders(id) });
  const casesTotal = useQuery({ queryKey: ["cases-total", id], queryFn: async () => (await listCases(id, { limit: 1, offset: 0 })).total });
  const labelOptions = useMemo(
    () => (labels.data ?? []).filter((l) => !/^ado-\d+$/.test(l.label)).map((l) => ({ value: l.label, label: `${l.label} (${l.count})` })),
    [labels.data],
  );
  const adoOptions = useMemo(
    () => (labels.data ?? []).flatMap((l) => {
      const m = /^ado-(\d+)$/.exec(l.label);
      return m ? [{ value: m[1], label: `#${m[1]} (${l.count})` }] : [];
    }),
    [labels.data],
  );
  const featureOptions = useMemo(
    () => (featureNames.data ?? []).map((f) => ({ value: f.feature, label: `${f.feature} (${f.count})` })),
    [featureNames.data],
  );

  // Picking a folder applies it together with whatever else is typed in the form; the grouping stays
  function submit(values: Values) {
    const next = new URLSearchParams();
    if (group === "scenario") next.set("group", "scenario");
    for (const k of FORM_KEYS) if (values[k].trim()) next.set(k, values[k].trim());
    setParams(next);
  }

  const pickFolder = (path: string) => submit({ ...form, folder: path });

  // Chips patch the applied URL (not the form draft) and go back to page 1
  function patchFilters(patch: Record<string, string>) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      next.delete("offset");
      return next;
    });
  }
  // A view switch keeps the filters and goes back to page 1
  function setGroup(to: Group) {
    if (to === group) return;
    patchFilters({ group: to === "scenario" ? "scenario" : "" });
  }
  const disclosureRef = useRef<HTMLDetailsElement>(null);
  // Clear all means a blank form: drafts in fields whose URL value did not change go too
  function clearAll() {
    setForm(read(new URLSearchParams()));
    setParams(group === "scenario" ? new URLSearchParams({ group: "scenario" }) : new URLSearchParams());
  }

  function apply(e: FormEvent) {
    e.preventDefault();
    submit(form);
  }

  const data = query.data?.page;
  // The Feature view's rows: from the server, or grouped here from the matching cases
  const featureRows = grouped ? features.data?.items : data ? groupByFeature(data.items) : undefined;
  const truncated = group === "feature" && listed && data != null && data.total > data.items.length;
  const total = grouped ? features.data?.total : group === "feature" ? featureRows?.length : data?.total;
  const active = grouped ? features : query;
  const stripKeys = useMemo(
    () => [...new Set((data?.items ?? []).flatMap((c) => (c.automated_test_key ? [c.automated_test_key] : [])))],
    [data],
  );
  const showLegend = group === "scenario" ? stripKeys.length > 0 : (featureRows ?? []).some((r) => (r.test_keys?.length ?? 0) > 0);
  const advancedActive = KEYS.filter((k) => k !== "q" && k !== "folder" && applied[k] !== "").length;
  const advancedHidden = KEYS.filter((k) => k !== "q" && k !== "folder" && applied[k] !== ""
    && !QUICK.some((c) => c.key === k && c.value === applied[k])).length;
  const filtered = KEYS.some((k) => applied[k] !== "");
  // One primary per view: the empty state's "Write the first case", Run on a selection, or the open Run likely affected
  // panel's Find tests take it from the header button; a selection takes it from Find tests
  const emptyList = total === 0 && !filtered;
  const newIsPrimary = !emptyList && picked.size === 0 && !impactOpen;

  return (
    <section>
      <PageHeader
        title="Test cases"
        headingRef={headingRef}
        tabs={[{ label: "Cases" }, { label: "Suites", to: "../suites" }]}
        actions={canEdit ? (
          <>
            <button ref={impactButtonRef} type="button" aria-expanded={impactOpen}
              aria-controls={impactOpen ? LIKELY_AFFECTED_ID : undefined} onClick={() => setImpactOpen((open) => !open)}>
              <Crosshair size={16} aria-hidden="true" /> Run likely affected
            </button>
            <Link className="button" to="import">
              <Upload size={16} aria-hidden="true" /> Import from Gherkin
            </Link>
            <Link className={newIsPrimary ? "button primary" : "button"} to="new">
              <Plus size={16} aria-hidden="true" /> New case
            </Link>
          </>
        ) : undefined}
      />
      <CasesKpis projectId={id} />
      <RunPanel projectId={id} />
      {canEdit && impactOpen && (
        <LikelyAffectedPanel id={LIKELY_AFFECTED_ID} projectId={id} primary={picked.size === 0} onClose={() => setImpactOpen(false)}
          onSelect={(cases) => setPicked(new Map(cases.map((c) => [c.number, { title: c.title, testKey: c.automated_test_key }])))} />
      )}

      <form onSubmit={apply}>
        <FilterBar>
          <div className="segmented-field">
            <span id="cases-group-label" className="segmented-label">Group by</span>
            <div className="segmented" role="group" aria-labelledby="cases-group-label">
              {(["feature", "scenario"] as const).map((g) => (
                <button key={g} type="button" aria-pressed={group === g} onClick={() => setGroup(g)}>
                  {g === "feature" ? "Feature" : "Scenario"}
                </button>
              ))}
            </div>
          </div>
          <label>
            Search
            <input type="search" value={form.q} onChange={(e) => setForm({ ...form, q: e.target.value })} placeholder={SEARCH_HINT[formSearchIn]} />
          </label>
          <label>
            Search in
            <select value={formSearchIn} onChange={(e) => setForm({ ...form, search_in: e.target.value })}>
              {SEARCH_IN.map((s) => <option key={s} value={s}>{SEARCH_IN_NAMES[s]}</option>)}
            </select>
          </label>
          <FolderSelect folders={folders.data ?? []} total={casesTotal.data} value={applied.folder} onChange={pickFolder} />
          <button type="submit">Apply</button>
        </FilterBar>
        <FiltersDisclosure id="cases" active={advancedActive} reveal={advancedHidden} detailsRef={disclosureRef}>
            <FilterSelect label="Label" value={form.label} options={labelOptions} onChange={(v) => setForm({ ...form, label: v })} />
            <FilterSelect label="Status" value={form.status} emptyLabel="Draft and ready" onChange={(v) => setForm({ ...form, status: v })}
              options={[{ value: "draft", label: "Draft" }, { value: "ready", label: "Ready" }, { value: "archived", label: "Archived" }]} />
            <FilterSelect label="Priority" value={form.priority} onChange={(v) => setForm({ ...form, priority: v })}
              options={PRIORITIES.map((p) => ({ value: p, label: p }))} />
            <FilterSelect label="Origin" value={form.origin} emptyLabel="All" onChange={(v) => setForm({ ...form, origin: v })}
              options={[{ value: "manual", label: "Manual" }, { value: "imported", label: "Imported" }]} />
            <FilterSelect label="Link" value={form.linked} onChange={(v) => setForm({ ...form, linked: v })}
              options={[{ value: "true", label: "Linked" }, { value: "false", label: "Not linked" }]} />
            <FilterSelect label="Latest result" value={form.result} onChange={(v) => setForm({ ...form, result: v })}
              options={[{ value: "passed", label: "Passed" }, { value: "failed", label: "Failed" }, { value: "skipped", label: "Skipped" }, { value: "never", label: "Never ran" }]} />
            <FilterSelect label="Feature" value={form.feature} options={featureOptions} onChange={(v) => setForm({ ...form, feature: v })} />
            <FilterSelect label="Azure DevOps" value={form.ado} options={adoOptions} onChange={(v) => setForm({ ...form, ado: v })} />
        </FiltersDisclosure>
      </form>
      <FilterChips quick={QUICK} values={applied} applied={appliedFilters(applied)} onChange={patchFilters}
        onClearAll={clearAll} onAddFilter={() => revealFilters(disclosureRef.current)} />

      {listed && query.data?.notice === "unavailable" && (
        <p className="error-banner" role="status">Latest result filter unavailable right now; showing the other filters.</p>
      )}
      {listed && query.data?.notice === "too-many" && (
        <p className="error-banner" role="status">Too many tests for the latest-result filter; showing the other filters.</p>
      )}
      {truncated && (
        <p className="muted" role="status">
          {`Grouped from the first ${data!.items.length} of ${data!.total} matching cases. `}
          <button type="button" className="ghost" onClick={() => setGroup("scenario")}>Show every case in Scenario view</button>
        </p>
      )}
      {active.error != null && <ErrorBanner error={active.error} onRetry={() => active.refetch()} />}
      {active.isPending && <p className="muted">Loading test cases…</p>}
      {total === 0 && (
        filtered ? (
          <p className="muted">No test cases match these filters.</p>
        ) : (
          <div className="card empty-state">
            <h2>No test cases yet</h2>
            <p className="muted">
              Write down what to check, step by step, and link each case to the automated test that covers it.
            </p>
            {canEdit && <Link className="button primary" to="new"><Plus size={16} aria-hidden="true" /> Write the first case</Link>}
          </div>
        )
      )}
      {total != null && total > 0 && (
        <>
        {showLegend && (
        <ul className="run-legend hide-narrow" aria-label="Last runs legend">
          {LEGEND.map(([kind, text]) => (
            <li key={kind}><span className={`run-bar bar-${kind}`} aria-hidden="true" /> {text}</li>
          ))}
        </ul>
        )}
        <div className={tableCardClass(card.wide)} ref={cardRef} tabIndex={0} role="region"
          aria-label={group === "feature" ? "Features" : "Test cases"} style={barHeight > 0 ? { paddingBottom: barHeight } : undefined}>
          {group === "feature" ? (
            <FeatureList projectId={id} rows={featureRows ?? []} selectable={!!canEdit} picked={picked} onToggle={toggle}
              onToggleAll={toggleAll} filters={featureFilters} />
          ) : (
            <CaseTable projectId={id} cases={data?.items ?? []} selectable={!!canEdit} picked={picked} onToggle={toggle} onToggleAll={toggleAll} />
          )}
          {group === "scenario" && data && (
            <div className="pager">
              <span className="muted">{offset + 1}–{offset + data.items.length} of {data.total}</span>
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - CASES_PAGE))}>Previous</button>
              <button disabled={offset + CASES_PAGE >= data.total} onClick={() => setOffset(offset + CASES_PAGE)}>Next</button>
            </div>
          )}
          {grouped && features.data && (
            <div className="pager">
              <span className="muted">{offset + 1}–{offset + features.data.items.length} of {features.data.total} features</span>
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - FEATURES_PAGE))}>Previous</button>
              <button disabled={offset + FEATURES_PAGE >= features.data.total} onClick={() => setOffset(offset + FEATURES_PAGE)}>Next</button>
            </div>
          )}
        </div>
        </>
      )}
      {/* After the table, so it appears below the rows instead of pushing them down; sticky keeps it in reach */}
      {canEdit && picked.size > 0 && (
        <div ref={barRef} className="run-selection" role="region" aria-label="Selected cases">
          <RunControl projectId={id} cases={[...picked].map(([number, p]) => ({ number, title: p.title, testKey: p.testKey }))}
            selection={{ case_numbers: [...picked.keys()] }} label={`Run selected (${picked.size})`}
            onStarted={() => { setPicked(new Map()); (tableRef.current ?? headingRef.current)?.focus(); }} />
          {selectionEstimate.data?.estimate_ms != null && (
            <span className="run-selection-estimate">{`· ${approxDuration(selectionEstimate.data.estimate_ms)}`}</span>
          )}
          <button type="button" className="ghost" onClick={() => setPicked(new Map())}>Clear selection</button>
          {picked.size >= MAX_RUN_CASES && <span className="muted">At most 200 cases per run</span>}
        </div>
      )}
    </section>
  );
}
