import { plural, testHistoryPath } from "./words";

test("a count with its noun, grouped as the locale groups it", () => {
  expect(plural(1, "test", "tests")).toBe("1 test");
  expect(plural(0, "test", "tests")).toBe("0 tests");
  expect(plural(1234, "run", "runs")).toBe("1,234 runs");
});

test("a test's history, on a branch when one is given", () => {
  expect(testHistoryPath(42, "a/b c")).toBe("/projects/42/tests/a%2Fb%20c");
  expect(testHistoryPath(42, "k", "feat/x")).toBe("/projects/42/tests/k?branch=feat%2Fx");
  expect(testHistoryPath(42, "k", null)).toBe("/projects/42/tests/k");
});
