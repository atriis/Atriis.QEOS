import { formatDuration } from "../api/analytics";
import type { Run, RunStage } from "../api/runs";
import { plural } from "./words";

const STAGE: Record<RunStage["name"], string> = { suggested: "suggested", rest: "the rest", all: "full suite" };

const seconds = (s: number): string => formatDuration(Math.round(s * 1000));

/** Only the suggested tests ran: `run-impact --suggested-only`, or a `--fail-fast` stop. */
export function isSubset(run: Pick<Run, "scope">): boolean {
  return run.scope === "impact-subset";
}

export function stoppedAfterStage1(run: Pick<Run, "stages">): boolean {
  return run.stages?.stopped_after_stage === 1;
}

/** The run page's line for a run uploaded by `run-impact` (spec 2026-10-13 §3.2); null for an ordinary upload. */
export function stagesLine(run: Pick<Run, "scope" | "stages">): string | null {
  const subset = isSubset(run);
  const s = run.stages ?? null;
  if (s === null) return subset ? "Suggested tests only" : null;
  const head = !subset ? "Suggested tests first"
    : stoppedAfterStage1(run) ? "Suggested tests only, stopped after stage 1" : "Suggested tests only";
  const stages = s.stages.map((stage, i) =>
    `stage ${i + 1} (${STAGE[stage.name]}) ${plural(stage.tests, "test", "tests")} in ${seconds(stage.duration_s)}`);
  const total = s.stages.reduce((sum, stage) => sum + stage.duration_s, 0);
  const failure = s.time_to_first_failure_s === null ? "no failures"
    : subset ? `first failure after ${seconds(s.time_to_first_failure_s)}`
    : `first failure after ${seconds(s.time_to_first_failure_s)} (full suite ${seconds(total)})`;
  return `${head}: ${[...stages, failure].join(" · ")}`;
}
