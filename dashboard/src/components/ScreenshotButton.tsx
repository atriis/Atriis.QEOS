import { useState } from "react";
import { Camera } from "lucide-react";
import ScreenshotViewer from "./ScreenshotViewer";

/** What the viewer opens: one result, on one step (or on its first image). */
export interface ShotTarget {
  projectId: number;
  runId: number;
  resultId: number;
  /** The test's name, for the viewer's title. */
  name: string;
  step?: { text: string; line: number | null };
}

/** One viewer per page, rendered at the page's level: a viewer rendered inside a Gherkin line would send its focus and
 *  key events, through the React tree, to the failed line's tip. */
export function useScreenshotViewer() {
  const [target, setTarget] = useState<ShotTarget | null>(null);
  const viewer = target && (
    <ScreenshotViewer projectId={target.projectId} runId={target.runId} resultId={target.resultId} name={target.name}
      initialStep={target.step} open onClose={() => setTarget(null)} />
  );
  return { open: setTarget, viewer };
}

interface Props {
  count: number;
  /** "step": a camera on a Gherkin line, the count shown above 1; "link": "Screenshots" by a result pill;
   *  "count": a camera and the count on a run's result row, named after the test (`name`). */
  kind: "step" | "link" | "count";
  name?: string;
  onOpen: () => void;
}

/** Opens a result's step screenshots (ADR-036); nothing is requested until it is pressed. */
export default function ScreenshotButton({ count, kind, name, onOpen }: Props) {
  // A row of a run's results names its test; on a case or a scenario card the test is the page's
  const accessible = kind === "step" ? `Screenshots for this step (${count})` : kind === "link" ? `Screenshots (${count})` : `Screenshots of ${name} (${count})`;
  return (
    <button type="button" className={`shot-button shot-button-${kind}`} aria-label={accessible} aria-haspopup="dialog" onClick={onOpen}>
      <Camera size={14} aria-hidden="true" />
      {kind === "link" && <span>Screenshots</span>}
      {(kind === "count" || count > 1) && <span className="shot-button-count">{count}</span>}
    </button>
  );
}
