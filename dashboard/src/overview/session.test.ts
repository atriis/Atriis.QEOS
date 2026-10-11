import type { OverviewLayoutState } from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";
import { startSession } from "./session";
import { BUILTIN_DEFAULT } from "./templates";

const MINE: StoredLayout = { schema: 1, widgets: [{ id: "m1", type: "flaky_count", size: "normal" }] };
const DEFAULT: StoredLayout = { schema: 1, widgets: [{ id: "d1", type: "latest_run", size: "wide" }] };
const project = { version: 4, updated_by: 7, updated_at: "2026-10-05T10:00:00Z", layout: DEFAULT };
const personalOver: OverviewLayoutState = {
  effective: MINE, source: "personal", personal: { version: 2, updated_at: "2026-10-01T10:00:00Z" }, project,
};

test("personal editing starts from what the user sees, with the project default as the reset target", () => {
  const session = startSession(personalOver, "personal");
  expect(session).toMatchObject({ mode: "personal", start: MINE, version: 2, fallback: DEFAULT, lastChange: null, openSettingsFor: null });
});

test("project editing starts from the project default even when a personal layout wins", () => {
  expect(startSession(personalOver, "project")).toMatchObject({
    mode: "project", start: DEFAULT, version: 4, fallback: BUILTIN_DEFAULT, defaultChangedAt: null,
    lastChange: { by: 7, at: "2026-10-05T10:00:00Z" },
  });
});

test("with nothing saved both modes start from the built-in default at version 0", () => {
  const builtin: OverviewLayoutState = { effective: null, source: "builtin", personal: null, project: null };
  expect(startSession(builtin, "personal")).toMatchObject({ start: BUILTIN_DEFAULT, version: 0, fallback: BUILTIN_DEFAULT });
  expect(startSession(builtin, "project")).toMatchObject({ start: BUILTIN_DEFAULT, version: 0, lastChange: null });
});

test("the default-changed date shows only when the default is newer than the personal layout", () => {
  expect(startSession(personalOver, "personal").defaultChangedAt).toBe("2026-10-05T10:00:00Z");
  const newerMine = { ...personalOver, personal: { version: 2, updated_at: "2026-10-06T10:00:00Z" } };
  expect(startSession(newerMine, "personal").defaultChangedAt).toBeNull();
});

test("widgets of unknown types are left out of the draft, and a widget's settings can open at once", () => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
  const odd: OverviewLayoutState = { ...personalOver, effective: { schema: 1, widgets: [...MINE.widgets, { id: "x", type: "gone_type", size: "wide" }] } };
  const session = startSession(odd, "personal", "m1");
  expect(session.start.widgets.map((w) => w.id)).toEqual(["m1"]);
  expect(session.openSettingsFor).toBe("m1");
});
