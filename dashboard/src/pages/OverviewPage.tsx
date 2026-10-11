import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { LayoutMode } from "../api/overviewLayout";
import ErrorBanner from "../components/ErrorBanner";
import PageHeader from "../components/PageHeader";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
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
  const id = Number(projectId);
  // The latest run decides between the widgets and "No runs yet"; a new one refreshes the figures that are not polled
  const { runs, latest } = useLatestRun(id);
  const { query: layout } = useOverviewLayout(id);
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

  async function reload() {
    if (session === null) return;
    const fresh = await layout.refetch();
    if (fresh.data) {
      setSession(startSession(fresh.data, session.mode));
      setSessionKey((k) => k + 1);
    }
  }

  // Customise needs the stored layout (plan Ruling 30) and a project with runs
  const canCustomise = session === null && layout.data !== undefined && latest !== undefined;

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
    if (session !== null) {
      return (
        <OverviewEditor key={sessionKey} projectId={id} session={session} onClose={() => setSession(null)} onReload={() => void reload()} />
      );
    }
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
        actions={canCustomise ? <CustomiseMenu canManage={false} triggerRef={customiseRef} onPick={(mode) => begin(mode)} /> : undefined}
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
