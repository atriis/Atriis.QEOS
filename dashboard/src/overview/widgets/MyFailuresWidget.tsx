import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatCount } from "../../api/analytics";
import { meQuery } from "../../api/auth";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { runsFirstPageQuery } from "../../lib/runQueries";
import { ago } from "../format";
import WidgetEmpty from "../WidgetEmpty";
import { myFailures } from "./myFailures";
import type { WidgetProps } from "./types";

/** Failed runs whose commit author is the signed-in person, matched by name: the collector stores `git log --format=%an`
 *  (spec §2.4). The default name is the QEOS full name; the setting holds the name as git records it. */
export default function MyFailuresWidget({ projectId, settings, heading, titleId, onOpenSettings }: WidgetProps) {
  const rows = settings.rows ?? 5;
  // A stored name that is only spaces counts as none: the QEOS full name applies
  const stored = settings.author?.trim() || undefined;
  const named = stored !== undefined;
  const me = useQuery({ ...meQuery, enabled: !named });
  const author = (stored ?? me.data?.full_name ?? "").trim();
  // An empty author would match every run (the filter is a substring match): never ask without a name (plan Ruling 24)
  const runs = useQuery({ ...runsFirstPageQuery(projectId, { status: "failing", author }), enabled: author !== "" });
  // The server matches a substring ("Ann" finds "Joanna"): keep only runs whose commit author is exactly the name
  const list = (runs.data ?? []).filter((run) => run.commit_author?.trim().toLowerCase() === author.toLowerCase());
  const waitingForName = !named && me.isPending;
  return (
    <>
      {heading}
      {(waitingForName || (author !== "" && runs.isPending)) && <SkeletonStat label="Loading your failures…" />}
      {!named && me.error != null && <ErrorBanner error={me.error} onRetry={() => me.refetch()} />}
      {!waitingForName && me.error == null && author === "" && (
        <WidgetEmpty onOpenSettings={onOpenSettings} titleId={titleId}>
          Your QEOS profile has no full name, so this widget cannot tell which runs are yours. Set "Your name in git" in
          its settings.
        </WidgetEmpty>
      )}
      {runs.error != null && <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />}
      {runs.data !== undefined && list.length === 0 && (
        <WidgetEmpty onOpenSettings={onOpenSettings} titleId={titleId}>
          No failed runs by “{author}”. If git records your name differently, set "Your name in git" in this widget's settings.
        </WidgetEmpty>
      )}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.slice(0, rows).map((run) => (
            <li key={run.id}>
              <span><Link to={`/projects/${projectId}/runs/${run.id}`}>Run #{run.id}</Link></span>
              <span className="where">
                {run.branch ?? "no branch"} · {ago(run.started_at)} · {formatCount(run.failed)} failed
                {run.errored > 0 && `, ${formatCount(run.errored)} errored`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={myFailures.link(projectId, settings)}>Failing runs <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
