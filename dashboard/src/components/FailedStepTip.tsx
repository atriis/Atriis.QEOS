import { Link } from "react-router-dom";
import type { LatestResult } from "../api/analytics";
import { ago } from "../overview/format";

/** What the failed-step tooltip says: the error, where and when it ran, and the way to the run. */
export default function FailedStepTip({ projectId, result }: { projectId: number; result: LatestResult }) {
  const meta = [result.branch, result.environment, ago(result.started_at)].filter(Boolean).join(" · ");
  return (
    <>
      <span>{result.message || "No error message"}</span>
      <span className="failed-tip-meta">{meta}</span>
      <Link to={`/projects/${projectId}/runs/${result.run_id}`}>Open run</Link>
    </>
  );
}
