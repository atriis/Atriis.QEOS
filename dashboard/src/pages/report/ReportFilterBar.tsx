import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { CaseAreas } from "../../api/cases";
import ErrorBanner from "../../components/ErrorBanner";
import FilterChips, { type QuickChip, revealFilters } from "../../components/FilterChips";
import FilterSelect from "../../components/FilterSelect";
import FolderSelect from "../../components/FolderSelect";
import PeriodRange from "../../components/PeriodRange";
import { CI_LABELS } from "../../lib/ciProviders";
import { AREA_KINDS, AREA_NAMES, type AreaKind, folderCounts, formatArea } from "../../lib/reportScope";
import { LINKED_ONLY, describeFilters, formatPeriod } from "./describeFilters";
import { ALL_BRANCHES, type FilterKey, PRESETS, type ReportFilters } from "./useReportFilters";
import { caseAreasMessage } from "./useReportRequest";

type Patch = Partial<Record<FilterKey, string>>;
const ORIGIN_HELP = "Requested from QEOS: runs started with Play, matched by their GitHub run. A Play whose run was never "
  + "matched counts as CI, and runs outside GitHub Actions are always CI.";

interface Props {
  filters: ReportFilters;
  update: (patch: Patch) => void;
  clearAll: () => void;
  today: string;
  defaultBranch: string | null;
  caseAreas: { data?: CaseAreas; error: unknown; isPending: boolean; refetch: () => unknown };
  runUrls: { error: unknown; refetch: () => unknown };
  /** The period's busiest values (summary.facets), offered in the branch and environment lists */
  facets?: { branches: string[]; environments: string[] };
}

/** One row above the sections (spec: Filter bar): period chips, a chip per filter in force, "+ Filter" and
 *  "Clear all"; "Custom…" opens a compact From–To row right under the chips, and the other filters sit in a
 *  disclosure that "+ Filter" opens. */
export default function ReportFilterBar({ filters, update, clearAll, today, defaultBranch, caseAreas, runUrls, facets }: Props) {
  const uid = useId();
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  // "Custom…" pressed while a preset is on: the range row shows until a range is applied or Cancel
  const [customOpen, setCustomOpen] = useState(false);
  const [draft, setDraft] = useState({ branch: "", allBranches: false, environment: "" });
  const [areaKind, setAreaKind] = useState<AreaKind | "">(filters.area?.kind ?? "");
  const areas = caseAreas.data;

  // The drafts follow the URL (Back, a chip removed, a pasted link)
  useEffect(() => {
    setDraft({
      branch: filters.branch === ALL_BRANCHES ? "" : filters.branch, allBranches: filters.branch === ALL_BRANCHES,
      environment: filters.environment,
    });
  }, [filters.branch, filters.environment]);
  useEffect(() => {
    setCustomOpen(false);
  }, [filters.preset, filters.from, filters.to]);
  // A filter in the URL picks its kind; clearing the value keeps the chosen kind, so the second step stays open
  useEffect(() => {
    if (filters.area) setAreaKind(filters.area.kind);
  }, [filters.area]);

  const custom = filters.preset === null;
  const quick: QuickChip[] = [
    ...PRESETS.map((p) => ({ key: "period", value: p, label: `${p} days` })),
    { key: "period", value: "custom", label: custom ? `Custom: ${formatPeriod(filters.from, filters.to)}` : "Custom…" },
  ];
  const applied = describeFilters(filters, defaultBranch, areas);
  const active = applied.filter((a) => !(a.key === "branch" && filters.branch === "")).length;

  function openForm() {
    revealFilters(detailsRef.current);
  }

  function onChipChange(patch: Record<string, string>) {
    if ("period" in patch) {
      if (patch.period === "custom") setCustomOpen(true);
      else if (patch.period) update({ period: patch.period });
      // "" (the pressed preset pressed again): a period is always set, so nothing changes
      return;
    }
    if ("branch" in patch && patch.branch === "") {
      // The default branch's chip goes to every branch; every other branch chip goes back to the default
      update({ branch: filters.branch === "" ? ALL_BRANCHES : "" });
      return;
    }
    update(patch as Patch);
  }

  function apply(e: FormEvent) {
    e.preventDefault();
    update({ branch: draft.allBranches ? ALL_BRANCHES : draft.branch.trim(), env: draft.environment.trim() });
  }

  const areaValue = (kind: AreaKind) => (filters.area?.kind === kind ? filters.area.value : "");
  const setArea = (kind: AreaKind, value: string) => update({ area: value ? formatArea({ kind, value }) : "" });

  return (
    <div className="report-filter-bar no-print">
      <FilterChips
        quick={quick}
        values={{ period: filters.preset ?? "custom" }}
        applied={applied}
        onChange={onChipChange}
        onClearAll={clearAll}
        onAddFilter={openForm}
      />
      {(custom || customOpen) && (
        <PeriodRange from={custom ? filters.from : ""} to={custom ? filters.to : ""} today={today} autoFocus={customOpen}
          onApply={(from, to) => update({ from, to })} onCancel={custom ? undefined : () => setCustomOpen(false)} />
      )}
      <details
        ref={detailsRef}
        className="more-filters"
        open={open}
        onToggle={(e) => {
          setOpen((e.currentTarget as HTMLDetailsElement).open);
        }}
      >
        <summary><ChevronRight size={14} aria-hidden="true" className="chevron" /> Filters{active > 0 && ` (${active} active)`}</summary>
        <form className="filters report-filter-form" onSubmit={apply} noValidate>
          <label>Branch
            <input list={`${uid}-branches`} value={draft.branch} maxLength={255} disabled={draft.allBranches}
              placeholder={defaultBranch ? `${defaultBranch} (default)` : ""}
              onChange={(e) => setDraft((d) => ({ ...d, branch: e.target.value }))} />
          </label>
          <datalist id={`${uid}-branches`}>{facets?.branches.map((b) => <option key={b} value={b} />)}</datalist>
          <label className="check-label">
            <input type="checkbox" checked={draft.allBranches} onChange={(e) => setDraft((d) => ({ ...d, allBranches: e.target.checked }))} />
            All branches
          </label>
          <label>Environment
            <input list={`${uid}-envs`} value={draft.environment} maxLength={100}
              onChange={(e) => setDraft((d) => ({ ...d, environment: e.target.value }))} />
          </label>
          <datalist id={`${uid}-envs`}>{facets?.environments.map((v) => <option key={v} value={v} />)}</datalist>
          <button type="submit" className="primary">Apply</button>

          <FilterSelect label="CI provider" value={filters.ci} onChange={(v) => update({ ci: v })}
            options={Object.entries(CI_LABELS).map(([value, label]) => ({ value, label }))} />
          <label>Origin
            <select value={filters.origin} onChange={(e) => update({ origin: e.target.value === "any" ? "" : e.target.value })}>
              <option value="any">Any</option>
              <option value="ci">CI</option>
              <option value="qeos">Requested from QEOS</option>
            </select>
          </label>
          <p className="muted filter-help">{ORIGIN_HELP}</p>
          {filters.origin !== "any" && runUrls.error != null && (
            <div><p>Play requests could not be loaded</p><ErrorBanner error={runUrls.error} onRetry={() => void runUrls.refetch()} /></div>
          )}

          <label>Area
            <select value={areaKind} disabled={!areas}
              onChange={(e) => {
                setAreaKind(e.target.value as AreaKind | "");
                if (filters.area) update({ area: "" });
              }}>
              <option value="">Any</option>
              {AREA_KINDS.map((k) => <option key={k} value={k}>{AREA_NAMES[k]}</option>)}
            </select>
          </label>
          {areas && areaKind === "feature" && (
            <FilterSelect label="Feature" value={areaValue("feature")} onChange={(v) => setArea("feature", v)}
              options={areas.features.map((f) => ({ value: f, label: f }))} />
          )}
          {areas && areaKind === "label" && (
            <FilterSelect label="Label" value={areaValue("label")} onChange={(v) => setArea("label", v)}
              options={areas.labels.map((l) => ({ value: l, label: l }))} />
          )}
          {areas && areaKind === "folder" && (
            <FolderSelect folders={folderCounts(areas)} value={areaValue("folder")} onChange={(p) => setArea("folder", p)} />
          )}
          {areas ? (
            <FilterSelect label="Suite" value={filters.suite === null ? "" : String(filters.suite)} onChange={(v) => update({ suite: v })}
              options={areas.suites.map((s) => ({ value: String(s.id), label: s.name }))} />
          ) : (
            <label>Suite<select disabled value=""><option value="">Any</option></select></label>
          )}
          {caseAreas.isPending && !caseAreas.error && <p className="muted filter-help">Loading areas and suites…</p>}
          {caseAreas.error != null && (
            <div><p>{caseAreasMessage(caseAreas.error)}</p><ErrorBanner error={caseAreas.error} onRetry={() => void caseAreas.refetch()} /></div>
          )}
          <p className="muted filter-help">{LINKED_ONLY}; the Coverage section counts the tests without a case.</p>
        </form>
      </details>
    </div>
  );
}
