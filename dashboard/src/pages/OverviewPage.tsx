import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { LayoutMode } from "../api/overviewLayout";
import ErrorBanner from "../components/ErrorBanner";
import PageHeader from "../components/PageHeader";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import { useCanManage } from "../lib/useCanEdit";
import CustomiseMenu from "../overview/CustomiseMenu";
import OverviewEditor from "../overview/OverviewEditor";
import { type EditSession, startSession } from "../overview/session";
import { BUILTIN_DEFAULT } from "../overview/templates";
import { useLatestRun } from "../overview/useLatestRun";
import { useOverviewLayout } from "../overview/useOverviewLayout";
import WidgetGrid from "../overview/WidgetGrid";

/** "What is broken now" in one screen, as widgets (spec 2026-10-11): the personal layout, else the project default,
 *  else the built-in four cards. Each widget loads, fails and retries on its own. Customise edits a draft of it
 *  (OverviewEditor). */
export default function OverviewPage() {
  const { projectId } = useParams();
  // One page per project: switching project (the breadcrumb reuses this route) starts afresh, so an edit session,
  // its snapshot and its version never cross projects. A dirty draft is asked about first by the unsaved-changes guard
  return <ProjectOverview key={projectId} id={Number(projectId)} />;
}

function ProjectOverview({ id }: { id: number }) {
  // The latest run decides between the widgets and "No runs yet"; a new one refreshes the figures that are not polled
  const { runs, latest } = useLatestRun(id);
  const { query: layout } = useOverviewLayout(id);
  // Owners and admins may also edit the project default (spec §2.3)
  const canManage = useCanManage(id);
  const [session, setSession] = useState<EditSession | null>(null);
  // A new key for every start, so Reload after a conflict always begins a fresh draft
  const [sessionKey, setSessionKey] = useState(0);
  const customiseRef = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);

  // Leaving edit mode hands focus back to Customise
  useEffect(() => {
    if (session === null && wasEditing.current) customiseRef.current?.focus();
    wasEditing.current = session !== null;
  }, [session]);

  function begin(mode: LayoutMode, openSettingsFor: string | null = null) {
    if (!layout.data) return;
    setSession(startSession(layout.data, mode, openSettingsFor));
    setSessionKey((k) => k + 1);
  }

  /** After a conflict: a fresh read of the stored layout, or a rejection (the editor keeps its draft and says why). */
  async function reload() {
    if (session === null) return;
    const fresh = await layout.refetch();
    // A failed refetch keeps the old cached data: never restart from it
    if (fresh.isError || !fresh.data) throw fresh.error ?? new Error("The layout could not be loaded");
    setSession(startSession(fresh.data, session.mode));
    setSessionKey((k) => k + 1);
  }

  // Customise needs the stored layout (plan Ruling 30) and a project with runs
  const canCustomise = session === null && layout.data !== undefined && latest !== undefined;

  // A failed poll keeps the runs it had: the page says so above what it shows rather than replacing it
  const runsError = runs.error != null && <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />;

  function body() {
    // The editor stays mounted whatever the polls do, so a draft is never lost
    if (session !== null) {
      return (
        <>
          {runsError}
          <OverviewEditor key={sessionKey} projectId={id} session={session} onClose={() => setSession(null)} onReload={reload} />
        </>
      );
    }
    if (runs.error != null && runs.data === undefined) return runsError;
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
        {runsError}
        {/* The layout could not be read: the built-in default is shown under this banner (plan Ruling 30) */}
        {layout.error != null && (
          <ErrorBanner
            error={layout.error}
            message="Your Overview layout could not be loaded, so the default is shown."
            onRetry={() => layout.refetch()}
          />
        )}
        <WidgetGrid
          projectId={id}
          layout={layout.data?.effective ?? BUILTIN_DEFAULT}
          // A widget's own "change the settings" button opens edit mode on that widget's settings
          onOpenSettings={canCustomise ? (widgetId) => begin("personal", widgetId) : undefined}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Overview"
        actions={canCustomise ? <CustomiseMenu canManage={canManage === true} triggerRef={customiseRef} onPick={(mode) => begin(mode)} /> : undefined}
      />
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
