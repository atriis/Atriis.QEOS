import type { LayoutRow, OverviewLayoutState } from "../api/overviewLayout";
import { afterReset, afterSave } from "./useOverviewLayout";

const A = { schema: 1, widgets: [{ id: "a", type: "latest_run", size: "wide" as const }] };
const B = { schema: 1, widgets: [{ id: "b", type: "my_suites", size: "normal" as const }] };
const row = (version = 2): LayoutRow => ({ layout: A, version, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
const builtin: OverviewLayoutState = { effective: null, source: "builtin", personal: null, project: null };
const withDefault: OverviewLayoutState = {
  effective: B, source: "project", personal: null,
  project: { version: 1, updated_by: 3, updated_at: "2026-10-01T00:00:00Z", layout: B },
};
const withPersonal: OverviewLayoutState = {
  ...withDefault, effective: A, source: "personal", personal: { version: 4, updated_at: "2026-10-02T00:00:00Z" },
};

test("a personal save becomes what this user sees", () => {
  expect(afterSave(withDefault, "personal", row(1))).toEqual({
    ...withDefault, effective: A, source: "personal", personal: { version: 1, updated_at: "2026-10-11T10:00:00Z" },
  });
});

test("a project save shows only when no personal layout wins", () => {
  const project = { version: 2, updated_by: 7, updated_at: "2026-10-11T10:00:00Z", layout: A };
  expect(afterSave(builtin, "project", row())).toEqual({ ...builtin, effective: A, source: "project", project });
  expect(afterSave(withPersonal, "project", row())).toEqual({ ...withPersonal, project });
});

test("resets fall back one level", () => {
  expect(afterReset(withPersonal, "personal")).toEqual({ ...withPersonal, personal: null, effective: B, source: "project" });
  expect(afterReset(withDefault, "project")).toEqual({ ...withDefault, project: null, effective: null, source: "builtin" });
  expect(afterReset(withPersonal, "project")).toEqual({ ...withPersonal, project: null });
  expect(afterReset({ ...withPersonal, project: null }, "personal")).toMatchObject({ effective: null, source: "builtin" });
});
