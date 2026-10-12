import type { ReactNode } from "react";
import { ApiError } from "../../api/http";
import type { Report } from "../../api/report";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import type { Gate } from "./useReportRequest";

/** What a section needs from its query (UseQueryResult<Report> fits; a section with its own answer names its type). */
export interface SectionQuery<T = Report> {
  data: T | undefined;
  error: unknown;
  isPending: boolean;
  refetch: () => unknown;
}

interface Props<T> {
  id: string;
  title: string;
  /** The Report's gate. A section that does not follow the Report's filters (Test impact) leaves it out. */
  gate?: Gate;
  query: SectionQuery<T>;
  /** The skeleton's height, so the page does not jump when the data arrives */
  height?: number;
  /** CSV buttons and grouping controls; never printed */
  actions?: ReactNode;
  /** A help line under the heading (what a figure counts, which filters do not apply) */
  note?: ReactNode;
  /** Whether the answer has nothing to show; by default a Report with no runs in scope */
  isEmpty?: (data: T) => boolean;
  /** The sentence for an empty answer */
  emptyText?: string;
  /** Extra content under the empty sentence */
  noRuns?: (data: T) => ReactNode;
  onResetFilters: () => void;
  children: (data: T) => ReactNode;
}

const noRunsInScope = (data: unknown) => (data as Report).scope.runs === 0;

function SectionError({ error, retry, reset }: { error: unknown; retry: () => unknown; reset: () => void }) {
  if (error instanceof ApiError && error.status === 422) {
    return (
      <div className="error-banner" role="alert">
        <span>These filters are not valid: {error.detail}</span>
        <button type="button" onClick={reset}>Reset filters</button>
      </div>
    );
  }
  // A 503 report_timeout carries its own sentence ("This report took too long. Narrow the period or the filters.")
  return <ErrorBanner error={error} onRetry={() => void retry()} />;
}

/** One report section: an h2-named region whose body is loading, blocked, an error with Retry, "no runs", or the data.
 *  An error is never shown as an empty period. */
export default function ReportSection<T = Report>({
  id, title, gate, query, height = 240, actions, note, isEmpty = noRunsInScope,
  emptyText = "No runs match these filters in this period", noRuns, onResetFilters, children,
}: Props<T>) {
  let body: ReactNode;
  if (gate?.state === "blocked") {
    body = gate.error != null
      ? <><p>{gate.message}</p><ErrorBanner error={gate.error} onRetry={gate.retry} /></>
      : <p className="muted">{gate.message}</p>;
  } else if (query.error != null) {
    body = <SectionError error={query.error} retry={query.refetch} reset={onResetFilters} />;
  } else if (gate?.state === "wait" || query.isPending || !query.data) {
    body = (
      <SkeletonStatus label={`Loading ${title.toLowerCase()}…`}>
        <span className="skeleton skeleton-block" style={{ height }} aria-hidden="true" />
      </SkeletonStatus>
    );
  } else if (isEmpty(query.data)) {
    body = (
      <div className="report-empty">
        <p className="muted">{emptyText}</p>
        {noRuns?.(query.data)}
      </div>
    );
  } else {
    body = children(query.data);
  }
  return (
    <section className="card report-section" aria-labelledby={id}>
      <div className="report-section-head">
        <h2 id={id}>{title}</h2>
        {actions != null && <div className="report-section-actions no-print">{actions}</div>}
      </div>
      {note != null && <p className="muted report-note">{note}</p>}
      {body}
    </section>
  );
}
