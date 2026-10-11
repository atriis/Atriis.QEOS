import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Clock, GitBranch, GitCommitHorizontal, Server } from "lucide-react";
import { formatDuration } from "../../api/analytics";
import RunStatusBadge from "../../components/RunStatusBadge";
import StatusDot from "../../components/StatusDot";
import { ago } from "../format";
import { failureGroupsQuery, latestRunQuery } from "../queries";
import type { WidgetProps } from "./types";

/** The latest run's verdict in words, what it ran on and its counts (today's card, unchanged). */
export default function LatestRunWidget({ projectId, heading }: WidgetProps) {
  const runs = useQuery(latestRunQuery(projectId));
  const latest = runs.data?.[0];
  const causes = useQuery(failureGroupsQuery(latest));
  // The page shows the "No runs yet" panel instead of the widgets, so this lasts at most one poll
  if (!latest) return <>{heading}</>;
  const broken = latest.failed + latest.errored;
  // Failures of quarantined tests are shown but do not decide the verdict
  const held = causes.data?.quarantined ?? 0;
  const blocking = causes.data?.blocking ?? broken;
  return (
    <>
      <div className="card-head">
        {heading}
        <RunStatusBadge verdict={blocking > 0 ? "failed" : "passed"} note={blocking === 0 && held > 0 ? `${held} quarantined` : undefined} />
      </div>
      {latest.commit_message && <p>{latest.commit_message}</p>}
      <div className="meta">
        {latest.branch && <span><GitBranch size={14} aria-hidden="true" /> {latest.branch}</span>}
        {latest.commit_sha && <span><GitCommitHorizontal size={14} aria-hidden="true" /> <code>{latest.commit_sha.slice(0, 7)}</code></span>}
        {latest.environment && <span><Server size={14} aria-hidden="true" /> {latest.environment}</span>}
        <span><Clock size={14} aria-hidden="true" /> {ago(latest.started_at)} · {formatDuration(latest.duration_ms)}</span>
      </div>
      <div className="meta">
        <span><StatusDot status="passed" label={`${latest.passed} passed`} /></span>
        <span><StatusDot status="failed" label={`${latest.failed} failed`} /></span>
        <span><StatusDot status="errored" label={`${latest.errored} errored`} /></span>
        <span><StatusDot status="skipped" label={`${latest.skipped} skipped`} /></span>
      </div>
      <div className="card-foot">
        <Link className="link-arrow" to={`/projects/${projectId}/runs/${latest.id}`}>Open run #{latest.id} <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
