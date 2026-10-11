import type { StoredLayout } from "./catalog";
import { type Draft, draftReducer, isDirty, nextWidgetId } from "./draft";

const layout = (ids: string[]): StoredLayout => ({
  schema: 1, widgets: ids.map((id) => ({ id, type: "latest_run", size: "normal", settings: {} })),
});
const draft = (ids: string[]): Draft => ({ layout: layout(ids), reset: false });
const ids = (d: Draft) => d.layout.widgets.map((w) => w.id);

test("move swaps with the neighbour and stops at the ends", () => {
  expect(ids(draftReducer(draft(["a", "b", "c"]), { kind: "move", id: "c", by: -1 }))).toEqual(["a", "c", "b"]);
  expect(ids(draftReducer(draft(["a", "b", "c"]), { kind: "move", id: "a", by: 1 }))).toEqual(["b", "a", "c"]);
  const start = draft(["a", "b"]);
  expect(draftReducer(start, { kind: "move", id: "a", by: -1 })).toBe(start);
  expect(draftReducer(start, { kind: "move", id: "b", by: 1 })).toBe(start);
});

test("size toggles between normal and wide", () => {
  const wide = draftReducer(draft(["a"]), { kind: "size", id: "a" });
  expect(wide.layout.widgets[0].size).toBe("wide");
  expect(draftReducer(wide, { kind: "size", id: "a" }).layout.widgets[0].size).toBe("normal");
});

test("remove drops the widget", () => {
  expect(ids(draftReducer(draft(["a", "b"]), { kind: "remove", id: "a" }))).toEqual(["b"]);
});

test("add appends with the given id, never past 24 widgets nor over a taken id", () => {
  const added = draftReducer(draft(["a"]), { kind: "add", id: "w2", type: "coverage", size: "normal", settings: { period: 30 } });
  expect(added.layout.widgets[1]).toEqual({ id: "w2", type: "coverage", size: "normal", settings: { period: 30 } });
  const full = draft(Array.from({ length: 24 }, (_, i) => `w${i + 1}`));
  expect(draftReducer(full, { kind: "add", id: "w25", type: "coverage", size: "normal", settings: {} })).toBe(full);
  const one = draft(["a"]);
  expect(draftReducer(one, { kind: "add", id: "a", type: "coverage", size: "normal", settings: {} })).toBe(one);
});

test("settings replace that widget's settings only", () => {
  const next = draftReducer(draft(["a", "b"]), { kind: "settings", id: "b", settings: { rows: 10 } });
  expect(next.layout.widgets.map((w) => w.settings)).toEqual([{}, { rows: 10 }]);
});

test("replace (a template) takes a copy, so editing the draft never changes the template", () => {
  const template = layout(["t1", "t2"]);
  const next = draftReducer(draft(["a"]), { kind: "replace", layout: template });
  expect(ids(next)).toEqual(["t1", "t2"]);
  const edited = draftReducer(next, { kind: "settings", id: "t1", settings: { rows: 5 } });
  expect(edited.layout.widgets[0].settings).toEqual({ rows: 5 });
  expect(template.widgets[0].settings).toEqual({});
});

test("reset marks the draft so Save deletes; any later edit clears the mark", () => {
  const reset = draftReducer(draft(["a"]), { kind: "reset", layout: layout(["d1"]) });
  expect(reset.reset).toBe(true);
  expect(ids(reset)).toEqual(["d1"]);
  expect(draftReducer(reset, { kind: "size", id: "d1" }).reset).toBe(false);
});

test("nextWidgetId skips ids in use", () => {
  expect(nextWidgetId(layout(["w1", "w3"]).widgets)).toBe("w4");
  expect(nextWidgetId(layout(["a", "b"]).widgets)).toBe("w3");
  expect(nextWidgetId([])).toBe("w1");
});

test("isDirty compares with where editing started", () => {
  const start = layout(["a", "b"]);
  const same: Draft = { layout: start, reset: false };
  expect(isDirty(same, start)).toBe(false);
  const moved = draftReducer(same, { kind: "move", id: "b", by: -1 });
  expect(isDirty(moved, start)).toBe(true);
  expect(isDirty(draftReducer(moved, { kind: "move", id: "b", by: 1 }), start)).toBe(false);
  expect(isDirty({ layout: start, reset: true }, start)).toBe(true);
});
