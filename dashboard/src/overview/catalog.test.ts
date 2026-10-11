import { CATALOG, MAX_WIDGETS, isValidSetting } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";

test("the dashboard reads the shared catalogue file", () => {
  expect(CATALOG.schema).toBe(1);
  expect(MAX_WIDGETS).toBe(24);
  expect(Object.keys(CATALOG.types)).toHaveLength(14);
  expect(CATALOG.types.my_failures.settings).toEqual(["author", "rows"]);
  expect(CATALOG.settings.branch).toEqual({ kind: "text", min_length: 1, max_length: 255 });
});

test("settings are checked against their allowed values", () => {
  expect(isValidSetting("rows", 10)).toBe(true);
  expect(isValidSetting("rows", 7)).toBe(false);
  expect(isValidSetting("rows", "5")).toBe(false);
  expect(isValidSetting("period", 14)).toBe(true);
  expect(isValidSetting("granularity", "month")).toBe(true);
  // A git branch named "all" is an ordinary branch: all branches is the absent key, not a magic value
  expect(isValidSetting("branch", "all")).toBe(true);
  expect(isValidSetting("branch", "")).toBe(false);
  expect(isValidSetting("branch", "x".repeat(255))).toBe(true);
  expect(isValidSetting("branch", "x".repeat(256))).toBe(false);
  expect(isValidSetting("branch", 5)).toBe(false);
  expect(isValidSetting("author", "a\u0000b")).toBe(false);
});

test("the built-in default is today's four cards, with every branch as an absent key", () => {
  expect(BUILTIN_DEFAULT.schema).toBe(CATALOG.schema);
  expect(BUILTIN_DEFAULT.widgets.map((w) => [w.type, w.size])).toEqual([
    ["latest_run", "wide"], ["failing_now", "normal"], ["pass_rate_week", "normal"], ["flaky_count", "normal"],
  ]);
  expect(BUILTIN_DEFAULT.widgets.find((w) => w.type === "pass_rate_week")?.settings).toEqual({});
  for (const widget of BUILTIN_DEFAULT.widgets) {
    for (const [name, value] of Object.entries(widget.settings ?? {})) {
      expect(isValidSetting(name as "rows", value)).toBe(true);
    }
  }
});
