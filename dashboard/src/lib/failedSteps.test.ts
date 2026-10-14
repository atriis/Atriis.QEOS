import type { RunFailedStep } from "../api/runs";
import { sinceText, spreadText, stepHref } from "./failedSteps";

const step = (extra: Partial<RunFailedStep> = {}): RunFailedStep => ({
  key: "a1b2c3d4e5f60718", by: "definition", pattern: "When I search {…}", cases: 12, errors: [],
  since: { run_id: 430, started_at: "2026-10-14T09:00:00Z", runs: 5, capped: false }, ...extra,
});

test("the run page says since when, how many runs, and the last pass", () => {
  expect(sinceText(step({ last_passed: { run_id: 429, started_at: "2026-10-13T09:00:00Z" } })))
    .toMatch(/^failing since run #430, .+ \(5 runs\) · last passed in run #429$/);
  expect(sinceText(step())).toMatch(/^failing since run #430, .+ \(5 runs\)$/);
});

test("a step new in this run says so, with the last pass when there is one", () => {
  const fresh = { run_id: 61, started_at: "2026-10-14T12:00:00Z", runs: 1, capped: false };
  expect(sinceText(step({ since: fresh }))).toBe("new in this run");
  expect(sinceText(step({ since: fresh, last_passed: { run_id: 60, started_at: "2026-10-14T11:00:00Z" } })))
    .toBe("new in this run · last passed in run #60");
});

test("a capped streak names its cap: 50 runs, else 90 days", () => {
  expect(sinceText(step({ since: { run_id: 12, started_at: "2026-08-01T00:00:00Z", runs: 50, capped: true } })))
    .toBe("failing for more than 50 runs");
  expect(sinceText(step({ since: { run_id: 12, started_at: "2026-07-20T00:00:00Z", runs: 3, capped: true } })))
    .toBe("failing for more than 90 days");
});

test("the tooltip line counts the other test cases", () => {
  expect(spreadText(step())).toBe("Also failed in 11 other test cases in this run · failing since run #430");
  expect(spreadText(step({ cases: 2 }))).toBe("Also failed in 1 other test case in this run · failing since run #430");
  expect(spreadText(step({ cases: 1, since: { run_id: 61, started_at: "2026-10-14T12:00:00Z", runs: 1, capped: false } })))
    .toBe("Only this test case · new in this run");
});

test("a step's link opens its row on the run page", () => {
  expect(stepHref(42, 61, "a1b2c3d4e5f60718")).toBe("/projects/42/runs/61#step-a1b2c3d4e5f60718");
});
