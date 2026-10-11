import { CATALOG, type SettingName, type WidgetType, isValidSetting } from "../catalog";
import { BUILTIN_DEFAULT, TEMPLATES } from "../templates";
import { REGISTRY, addableDefinitions, definitionOf, withDefaults, widgetTitle } from "./registry";

test("the registry has a widget for every catalogue type, and no other", () => {
  expect(Object.keys(REGISTRY).sort()).toEqual(Object.keys(CATALOG.types).sort());
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
  expect(addableDefinitions().map((def) => def.type)).toEqual(Object.keys(CATALOG.types).filter((type) => Object.hasOwn(REGISTRY, type)));
});

test("each template is a valid stored layout of registered widgets, with no branch (every branch)", () => {
  expect(TEMPLATES.map((t) => t.label)).toEqual(["QA lead", "Developer", "Flaky hunt"]);
  const idPattern = new RegExp(CATALOG.widget_id_pattern);
  for (const template of TEMPLATES) {
    const { widgets } = template.layout;
    expect(template.layout.schema).toBe(CATALOG.schema);
    expect(widgets.length).toBeLessThanOrEqual(CATALOG.max_widgets);
    expect(new Set(widgets.map((w) => w.id)).size).toBe(widgets.length);
    for (const widget of widgets) {
      expect(widget.id).toMatch(idPattern);
      expect(CATALOG.sizes).toContain(widget.size);
      const def = REGISTRY[widget.type as WidgetType];
      expect(def).toBeDefined();
      for (const [name, value] of Object.entries(widget.settings ?? {})) {
        expect(def!.settings).toContain(name);
        expect(isValidSetting(name as SettingName, value)).toBe(true);
      }
      expect(widget.settings?.branch).toBeUndefined();
    }
  }
});
