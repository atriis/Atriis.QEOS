import { Link, useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import ErrorBanner from "../components/ErrorBanner";
import PageHeader from "../components/PageHeader";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import { BUILTIN_DEFAULT } from "../overview/templates";
import { useLatestRun } from "../overview/useLatestRun";
import { useOverviewLayout } from "../overview/useOverviewLayout";
import WidgetGrid from "../overview/WidgetGrid";

/** "What is broken now" in one screen, as widgets (spec 2026-10-11): the personal layout, else the project default,
 *  else the built-in four cards. Each widget loads, fails and retries on its own. */
export default function OverviewPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  // The latest run decides between the widgets and "No runs yet"; a new one refreshes the figures that are not polled
  const { runs, latest } = useLatestRun(id);
  const { query: layout } = useOverviewLayout(id);

  function body() {
    if (runs.error != null) return <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />;
    if (runs.isPending || layout.isPending) {
      return (
        <SkeletonStatus label="Loading overview…" className="overview-grid">
          <SkeletonCard className="wide" height={96} />
          <SkeletonCard height={120} />
          <SkeletonCard height={120} />
          <SkeletonCard height={120} />
        </SkeletonStatus>
      );
    }
    if (!latest) return <NoRunsYet projectId={id} />;
    return (
      <>
        {/* The layout could not be read: the built-in default is shown under this banner (plan Ruling 30) */}
        {layout.error != null && (
          <ErrorBanner
            error={layout.error}
            message="Your Overview layout could not be loaded, so the default is shown."
            onRetry={() => layout.refetch()}
          />
        )}
        <WidgetGrid projectId={id} layout={layout.data?.effective ?? BUILTIN_DEFAULT} />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Overview" />
      {body()}
    </>
  );
}

/** Shown instead of the widgets until the first upload (spec §2.7). */
function NoRunsYet({ projectId }: { projectId: number }) {
  return (
    <div className="card">
      <h2>No runs yet</h2>
      <p className="muted">
        Results appear here after the first upload from CI. Create an API key, paste the CI
        snippet into your pipeline, and the next build reports its tests.
      </p>
      <Link className="link-arrow" to={`/projects/${projectId}/settings`}>Set up an API key and CI <ArrowRight size={14} aria-hidden="true" /></Link>
    </div>
  );
}
