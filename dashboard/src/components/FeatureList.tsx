import { Fragment, type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronRight } from "lucide-react";
import type { CaseQuery } from "../api/cases";
import { type FeatureRow, STATUS_ORDER, fileLabel, groupCasesQuery } from "../lib/featureQueries";
import { CaseRow, type CaseRowData, isRunnable, useFeatureStrips, useRunStrips } from "./CaseTable";
import ErrorBanner from "./ErrorBanner";
import NarrowMeta from "./NarrowMeta";
import { CaseStatusPill } from "./StatusPill";

export const MANUAL_GROUP = "No feature (manual)";

/** A feature row's name: its Feature, else its file name; the manual group has its own label. */
export const featureLabel = (row: { feature_name: string | null; path: string | null }) =>
  row.path == null ? MANUAL_GROUP : row.feature_name || fileLabel(row.path);

/** The Automated cell as plain text, for the narrow meta line. */
function automatedText(row: FeatureRow) {
  const linked = row.linked_count;
  if (linked == null) return null;
  return linked === 0 ? "Manual" : linked >= row.case_count ? "All linked" : `${linked} of ${row.case_count} linked`;
}

/** The group's statuses: one pill when they all agree, else "2 ready · 1 draft" as quiet text. Empty when unknown. */
function statusCell(row: FeatureRow) {
  const counts = row.status_counts;
  if (!counts) return null;
  const present = STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0);
  if (present.length === 0) return null;
  if (present.length === 1) return <CaseStatusPill status={present[0]} />;
  return <span className="muted">{present.map((s) => `${counts[s]} ${s}`).join(" · ")}</span>;
}

/** Linked cases of the group: "All linked", "Manual" or "3 of 5 linked". Empty when unknown. */
function automatedCell(row: FeatureRow) {
  const linked = row.linked_count;
  if (linked == null) return null;
  if (linked === 0) return <span className="muted">Manual</span>;
  if (linked >= row.case_count) return <span className="linked"><Bot size={14} aria-hidden="true" /> All linked</span>;
  return <span>{linked} of {row.case_count} linked</span>;
}

interface Props {
  projectId: number;
  rows: FeatureRow[];
  selectable: boolean;
  picked: ReadonlyMap<number, unknown>;
  onToggle: (c: CaseRowData) => void;
  onToggleAll: (on: boolean, rows: CaseRowData[]) => void;
  /** The filters in force, for the manual group's cases. */
  filters: Omit<CaseQuery, "limit" | "offset">;
}

/** The Feature view of the Cases list: one row per .feature file, expanding in place to its scenarios. */
export default function FeatureList({ projectId, rows, selectable, picked, onToggle, onToggleAll, filters }: Props) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const qc = useQueryClient();
  const { lastRuns, lastRunsSummary } = useFeatureStrips(projectId, rows);
  const idOf = (row: FeatureRow) => row.path ?? "\0manual";
  // The Scenario view's columns: Title, Last runs, Priority, Status, Automated
  const columns = (selectable ? 1 : 0) + 5;

  function flip(row: FeatureRow) {
    const next = new Set(open);
    if (!next.delete(idOf(row))) next.add(idOf(row));
    setOpen(next);
  }

  // Checking a feature selects every runnable scenario it holds; the titles come with its cases
  async function pickRow(row: FeatureRow, on: boolean) {
    const cases = await qc.fetchQuery(groupCasesQuery(projectId, row, filters));
    onToggleAll(on, cases.filter(isRunnable));
  }

  // The header box covers every feature on the page; the manual group has nothing to run
  const features = rows.filter((row) => row.path != null);
  const numbers = features.flatMap((row) => row.case_numbers);
  const shownAll = numbers.filter((n) => picked.has(n)).length;
  async function pickAll(on: boolean) {
    const groups = await Promise.all(features.map((row) => qc.fetchQuery(groupCasesQuery(projectId, row, filters))));
    onToggleAll(on, groups.flat().filter(isRunnable));
  }

  return (
    <table className="data cases-table feature-list">
      <thead>
        <tr>
          {selectable && (
            <th className="select-col col-select">
              {features.length > 0 ? (
                <input type="checkbox" aria-label="Select every scenario on this page"
                  checked={shownAll > 0 && shownAll === numbers.length}
                  ref={(el) => { if (el) el.indeterminate = shownAll > 0 && shownAll < numbers.length; }}
                  onChange={(e) => void pickAll(e.target.checked)} />
              ) : <span className="sr-only">Select</span>}
            </th>
          )}
          <th className="col-title">Title</th><th className="hide-narrow col-runs">Last runs</th>
          <th className="hide-narrow col-priority">Priority</th><th className="col-status">Status</th><th className="hide-narrow col-automated">Automated</th>
        </tr>
      </thead>
      {rows.map((row) => {
        const label = featureLabel(row);
        const expanded = open.has(idOf(row));
        const shown = row.case_numbers.filter((n) => picked.has(n)).length;
        return (
          <Fragment key={idOf(row)}>
            <tbody className="feature-group">
              <tr className="feature-row">
                {selectable && (
                  <td className="select-col">
                    {row.path != null && (
                      <input type="checkbox" aria-label={`Select every scenario of ${label}`}
                        checked={shown > 0 && shown === row.case_numbers.length}
                        ref={(el) => { if (el) el.indeterminate = shown > 0 && shown < row.case_numbers.length; }}
                        onChange={(e) => void pickRow(row, e.target.checked)} />
                    )}
                  </td>
                )}
                <td className="wrap-anywhere">
                  <div className="feature-head">
                    <button type="button" className="disclosure" aria-expanded={expanded} aria-label={`Show scenarios of ${label}`}
                      onClick={() => flip(row)}>
                      <ChevronRight size={16} aria-hidden="true" />
                    </button>
                    <span className="feature-text">
                      {row.path != null ? (
                        <Link className="feature-name truncate" title={label} to={`/projects/${projectId}/cases/feature?path=${encodeURIComponent(row.path)}`}>{label}</Link>
                      ) : (
                        <span className="feature-name truncate" title={label}>{label}</span>
                      )}
                      {row.folder ? <span className="feature-folder truncate" title={row.folder}>{row.folder}</span> : null}
                      <NarrowMeta items={[
                        { label: "Last runs", value: lastRunsSummary(row) },
                        { label: "Priority", value: row.top_priority },
                        { label: "Automated", value: automatedText(row) },
                      ]} />
                    </span>
                  </div>
                </td>
                <td className="hide-narrow">
                  <div className="feature-runs">
                    {lastRuns(row)}
                  </div>
                </td>
                {/* Aggregates of the group's matching scenarios: its highest priority, its statuses, how many are linked */}
                <td className="hide-narrow">
                  {row.top_priority && <span aria-label={`Highest priority: ${row.top_priority}`}>{row.top_priority}</span>}
                </td>
                <td>{statusCell(row)}</td>
                <td className="hide-narrow">{automatedCell(row)}</td>
              </tr>
            </tbody>
            {expanded && (
              <GroupCases projectId={projectId} row={row} label={`Scenarios of ${label}`} selectable={selectable}
                picked={picked} onToggle={onToggle} filters={filters} columns={columns} />
            )}
          </Fragment>
        );
      })}
    </table>
  );
}

/** A feature's scenarios as rows of the same table, so they line up under the feature's columns. */
function GroupCases({ projectId, row, label, selectable, picked, onToggle, filters, columns }: {
  projectId: number; row: FeatureRow; label: string; selectable: boolean; picked: ReadonlyMap<number, unknown>;
  onToggle: (c: CaseRowData) => void; filters: Omit<CaseQuery, "limit" | "offset">; columns: number;
}) {
  const cases = useQuery(groupCasesQuery(projectId, row, filters));
  const { lastRuns, lastRunsSummary } = useRunStrips(projectId, useMemo(() => (cases.data ?? []).map((c) => c.automated_test_key), [cases.data]));
  const note = (content: ReactNode) => <tr className="feature-note"><td colSpan={columns}>{content}</td></tr>;
  return (
    <tbody className="feature-cases" aria-label={label}>
      {cases.error != null ? note(<ErrorBanner error={cases.error} onRetry={() => cases.refetch()} />)
        : !cases.data ? note(<span className="muted">Loading scenarios…</span>)
        : (
          <>
            {cases.data.map((c) => (
              <CaseRow key={c.number} className="scenario-row" nested projectId={projectId} c={c} selectable={selectable} picked={picked}
                onToggle={onToggle} lastRuns={lastRuns} lastRunsSummary={lastRunsSummary} />
            ))}
            {row.case_count > cases.data.length && note(
              <span className="muted">
                {`Showing ${cases.data.length} of ${row.case_count}. `}
                <Link to={`/projects/${projectId}/cases?group=scenario${row.path == null ? "&origin=manual" : `&feature=${encodeURIComponent(row.feature_name ?? "")}`}`}>
                  See them all in Scenario view
                </Link>
              </span>,
            )}
            {cases.data.length === 0 && note(<span className="muted">No scenarios match the filters.</span>)}
          </>
        )}
    </tbody>
  );
}
