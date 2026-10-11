import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { ApiError } from "./http";
import { conflictOf, deleteLayout, getOverviewLayout, saveLayout } from "./overviewLayout";

const LAYOUT = { schema: 1, widgets: [{ id: "w1", type: "latest_run", size: "wide" as const }] };

beforeEach(() => setAccessToken("acc"));

test("reads the layout state", async () => {
  server.use(http.get("/api/v1/projects/42/overview-layout", () =>
    HttpResponse.json({ effective: null, source: "builtin", personal: null, project: null })));
  await expect(getOverviewLayout(42)).resolves.toEqual({ effective: null, source: "builtin", personal: null, project: null });
});

test("saves a personal or project layout with the version editing started from", async () => {
  const sent: { mode: string; body: unknown }[] = [];
  server.use(http.put("/api/v1/projects/42/overview-layout/:mode", async ({ request, params }) => {
    sent.push({ mode: String(params.mode), body: await request.json() });
    return HttpResponse.json({ layout: LAYOUT, version: 3, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  await expect(saveLayout(42, "personal", LAYOUT, 2)).resolves.toMatchObject({ version: 3 });
  await saveLayout(42, "project", LAYOUT, 0);
  expect(sent).toEqual([
    { mode: "personal", body: { layout: LAYOUT, version: 2 } },
    { mode: "project", body: { layout: LAYOUT, version: 0 } },
  ]);
});

test("deletes a layout", async () => {
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  await expect(deleteLayout(42, "project")).resolves.toBeUndefined();
  expect(deleted).toEqual(["project"]);
});

test("a stale save is a 409 whose stored version conflictOf reads", async () => {
  const current = { version: 5, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" };
  server.use(http.put("/api/v1/projects/42/overview-layout/:mode", () => HttpResponse.json(
    { detail: { code: "stale_version", message: "The layout changed since you started", current } }, { status: 409 },
  )));
  const error = await saveLayout(42, "project", LAYOUT, 4).catch((e: unknown) => e);
  expect(conflictOf(error)).toEqual(current);
});

test("conflictOf reads the stored version a stale save names, and nothing from other errors", () => {
  const current = { version: 5, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" };
  expect(conflictOf(new ApiError(409, "Changed", "stale_version", { detail: { code: "stale_version", current } }))).toEqual(current);
  expect(conflictOf(new ApiError(409, "Changed", "stale_version", { detail: { code: "stale_version", current: null } }))).toBeNull();
  expect(conflictOf(new ApiError(409, "Duplicate"))).toBeUndefined();
  expect(conflictOf(new ApiError(422, "schema must be 1"))).toBeUndefined();
  expect(conflictOf(new Error("boom"))).toBeUndefined();
});
