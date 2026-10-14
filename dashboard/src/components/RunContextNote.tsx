import { History } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { dateFormat } from "../lib/words";

/** Opened from a Last runs bar: says which run the page shows, and links back to the latest results. */
export default function RunContextNote({ projectId, runId, startedAt, status, missing, error, latestHref }: {
  projectId: number;
  runId: number;
  /** The run's start, once a result from it is known. */
  startedAt?: string;
  /** The case's status in the run; left out on a feature page, where each scenario says its own. */
  status?: string;
  /** Shown instead of the status when the test was not in the run. */
  missing?: string;
  error?: unknown;
  latestHref: string;
}) {
  const run = <Link to={`/projects/${projectId}/runs/${runId}`}>run #{runId}</Link>;
  const text = error instanceof ApiError && error.status === 404
    ? <>Run #{runId} is not in this project.</>
    : error != null
      ? <>The results of run #{runId} could not be loaded.</>
      : missing
        ? <>{missing}</>
        : <>Showing {run}{startedAt ? `, ${dateFormat.format(new Date(startedAt))}` : ""}{status ? `: ${status}` : ""}.</>;
  return (
    <p className="note run-context" role="note">
      <History size={16} aria-hidden="true" />
      <span>{text} <Link to={latestHref}>Show latest</Link></span>
    </p>
  );
}
