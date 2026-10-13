import type { RunStages } from "../api/runs";
import { isSubset, stagesLine, stoppedAfterStage1 } from "./runScope";

const two: RunStages = {
  stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }, { name: "rest", duration_s: 850, tests: 340, failed: 0 }],
  time_to_first_failure_s: 42.5,
  stopped_after_stage: null,
};
const stopped: RunStages = {
  stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }],
  time_to_first_failure_s: 30,
  stopped_after_stage: 1,
};

test("a two-stage run names both stages and when the first failure came", () => {
  expect(stagesLine({ scope: "full", stages: two })).toBe(
    "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) 340 tests in 14m 10s"
    + " · first failure after 42.5 s (full suite 15m 15s)");
});

test("a run without failures says so", () => {
  expect(stagesLine({ scope: "full", stages: { ...two, time_to_first_failure_s: null } })).toBe(
    "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) 340 tests in 14m 10s · no failures");
});

test("a run with nothing to suggest ran the full suite as one stage", () => {
  const all: RunStages = { stages: [{ name: "all", duration_s: 900, tests: 352, failed: 0 }], time_to_first_failure_s: null,
    stopped_after_stage: null };
  expect(stagesLine({ scope: "full", stages: all })).toBe("Suggested tests first: stage 1 (full suite) 352 tests in 15m 00s · no failures");
});

test("a fail-fast stop is suggested tests only, stopped after stage 1", () => {
  expect(stagesLine({ scope: "impact-subset", stages: stopped })).toBe(
    "Suggested tests only, stopped after stage 1: stage 1 (suggested) 12 tests in 1m 05s · first failure after 30.0 s");
});

test("a suggested-only run without stages still says what it was", () => {
  expect(stagesLine({ scope: "impact-subset", stages: null })).toBe("Suggested tests only");
});

test("an ordinary upload, or an older server, has no line", () => {
  expect(stagesLine({ scope: "full", stages: null })).toBeNull();
  expect(stagesLine({})).toBeNull();
});

test("one test is singular", () => {
  const one: RunStages = { stages: [{ name: "suggested", duration_s: 2, tests: 1, failed: 0 }], time_to_first_failure_s: null,
    stopped_after_stage: null };
  expect(stagesLine({ scope: "impact-subset", stages: one })).toBe("Suggested tests only: stage 1 (suggested) 1 test in 2.0 s · no failures");
});

test("isSubset and stoppedAfterStage1", () => {
  expect(isSubset({ scope: "impact-subset" })).toBe(true);
  expect(isSubset({ scope: "full" })).toBe(false);
  expect(isSubset({})).toBe(false);
  expect(stoppedAfterStage1({ stages: stopped })).toBe(true);
  expect(stoppedAfterStage1({ stages: two })).toBe(false);
  expect(stoppedAfterStage1({ stages: null })).toBe(false);
});

test("a separator never starts a line: it is bound to the item before it", () => {
  const line = stagesLine({ scope: "full", stages: two })!;
  expect(line.match(/·/g)).toHaveLength(2);
  expect(line).not.toMatch(/[ \t\n]·/); // only a no-break space before each separator, so a wrap comes after it
  expect(line).toContain("1m 05s · stage 2");
});
