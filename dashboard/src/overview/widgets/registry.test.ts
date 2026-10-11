import { CATALOG, type SettingName, type WidgetType, isValidSetting } from "../catalog";
import { BUILTIN_DEFAULT } from "../templates";
import { REGISTRY, addableDefinitions, definitionOf, withDefaults, widgetTitle } from "./registry";

// Catalogue types whose widgets arrive in Phase 3; each of Tasks 16-20 removes its own, Task 21 removes the set
const PENDING = new Set<string>([
  "recent_runs", "branch_health",
  "case_tiles", "my_failures", "my_suites",
]);

test("the registry has a widget for every catalogue type, and no other", () => {
  const expected = Object.keys(CATALOG.types).filter((type) => !PENDING.has(type)).sort();
  expect(Object.keys(REGISTRY).sort()).toEqual(expected);
});

test("each widget declares exactly its catalogue settings, with allowed defaults", () => {
  for (const [type, def] of Object.entries(REGISTRY)) {
    expect(def.type).toBe(type);
    expect([...def.settings].sort()).toEqual([...CATALOG.types[type as WidgetType].settings].sort());
    for (const [name, value] of Object.entries(def.defaults)) {
      expect(def.settings).toContain(name);
      expect(isValidSetting(name as SettingName, value)).toBe(true);
    }
    expect(CATALOG.sizes).toContain(def.defaultSize);
  }
});

test("the built-in default places registered widgets with their own, allowed settings", () => {
  for (const widget of BUILTIN_DEFAULT.widgets) {
    const def = REGISTRY[widget.type as WidgetType];
    expect(def).toBeDefined();
    for (const [name, value] of Object.entries(widget.settings ?? {})) {
      expect(def!.settings).toContain(name);
      expect(isValidSetting(name as SettingName, value)).toBe(true);
    }
  }
});

test("stored settings overlay the defaults only where still allowed; an absent branch stays absent", () => {
  const flaky = definitionOf("flaky_count")!;
  expect(withDefaults(flaky, { period: 30 })).toEqual({ period: 30 });
  expect(withDefaults(flaky, { period: 99 })).toEqual({ period: 14 });
  expect(withDefaults(flaky, undefined)).toEqual({ period: 14 });
  const passRate = definitionOf("pass_rate_week")!;
  expect(withDefaults(passRate, {})).toEqual({});
  expect(withDefaults(passRate, { branch: "main", rows: 10 })).toEqual({ branch: "main" });
});

test("titles follow the settings, and Add widget offers registered types in catalogue order", () => {
  expect(widgetTitle({ id: "a", type: "flaky_count", size: "normal", settings: { period: 7 } })).toBe("Flaky tests, last 7 days");
  expect(widgetTitle({ id: "b", type: "failing_now", size: "normal" })).toBe("Failing in latest run");
  expect(addableDefinitions().map((def) => def.type)).toEqual(["latest_run", "failing_now", "pass_rate_week", "flaky_count", "pass_rate_trend", "failure_causes", "regressions", "slowest_tests", "coverage"]);
});
