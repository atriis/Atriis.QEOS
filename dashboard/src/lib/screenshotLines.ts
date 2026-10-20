import type { LatestResult } from "../api/analytics";
import { type FailedStep, type StepLine, locateFailedStep } from "./failedStep";

export type ScreenshotStep = NonNullable<LatestResult["screenshot_steps"]>[number];
/** The shown line a step that ran lands on, or null when it is not shown there. */
export type Locate = (step: FailedStep) => number | null;
/** One camera button: every image on that line, and the step the viewer opens on. */
export interface PlacedShots { count: number; step: { text: string; line: number | null } }

/** Where a result's screenshots go in the shown Gherkin (ADR-036), matched as the failed step is (text, then line):
 *  one entry per line, its own images and any hook group placed on that step counted together. `unplaced` counts the
 *  images of steps that are not shown (edited since the run, or a Background the page shows once for every scenario). */
export function placeScreenshots(lines: StepLine[] | Locate, steps: ScreenshotStep[] | undefined): { byLine: Map<number, PlacedShots>; unplaced: number } {
  const locate: Locate = typeof lines === "function" ? lines : (step) => {
    const at = locateFailedStep(lines, step);
    return at == null ? null : lines[at].line;
  };
  const byLine = new Map<number, PlacedShots>();
  let unplaced = 0;
  for (const s of steps ?? []) {
    const line = locate({ text: s.step_text, line: s.step_line ?? undefined });
    if (line == null) { unplaced += s.count; continue; }
    const placed = byLine.get(line);
    const step = { text: s.step_text, line: s.step_line };
    // The viewer opens on the step's own image first, so a hook group never decides where it opens
    if (!placed) byLine.set(line, { count: s.count, step });
    else byLine.set(line, { count: placed.count + s.count, step: s.hook === null ? step : placed.step });
  }
  return { byLine, unplaced };
}
