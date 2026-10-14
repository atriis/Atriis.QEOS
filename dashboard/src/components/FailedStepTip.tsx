import { Link } from "react-router-dom";
import type { LatestResult } from "../api/analytics";
import type { StepSpread } from "../lib/failedSteps";
import { ago } from "../overview/format";

/** What the failed-step tooltip says: the error, how wide the step failed in that run (linking to its row on the run
 *  page), where and when it ran, and the way to the run. */
export default function FailedStepTip({ projectId, result, spread }: { projectId: number; result: LatestResult; spread?: StepSpread }) {
  const meta = [result.branch, result.environment, ago(result.started_at)].filter(Boolean).join(" · ");
  return (
    <>
      <span>{result.message || "No error message"}</span>
      {spread && <Link className="failed-tip-spread" to={spread.href}>{spread.text}</Link>}
      <span className="failed-tip-meta">{meta}</span>
      <Link to={`/projects/${projectId}/runs/${result.run_id}`}>Open run</Link>
    </>
  );
}
