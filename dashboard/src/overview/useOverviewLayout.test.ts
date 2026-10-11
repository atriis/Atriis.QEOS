import { createElement, type ReactElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { type LayoutRow, type OverviewLayoutState, conflictOf } from "../api/overviewLayout";
import { afterReset, afterSave, layoutKey, useOverviewLayout } from "./useOverviewLayout";

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

describe("useOverviewLayout against the API", () => {
  const STATE: OverviewLayoutState = withDefault;
  let gets = 0;
  let release: () => void;
  let wrapper: ({ children }: { children: ReactNode }) => ReactElement;
  let client: QueryClient;

  beforeEach(() => {
    setAccessToken("acc");
    gets = 0;
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    wrapper = ({ children }) => createElement(QueryClientProvider, { client }, children);
    // The server's state never changes here, and a refetch waits for release(): whatever the cache shows after a
    // save or reset came from the hook, and `gets` counts the refetch as soon as it is asked
    const gate = new Promise<void>((resolve) => { release = resolve; });
    server.use(http.get("/api/v1/projects/42/overview-layout", async () => {
      gets += 1;
      if (gets > 1) await gate;
      return HttpResponse.json(STATE);
    }));
  });

  async function mounted() {
    const hook = renderHook(() => useOverviewLayout(42), { wrapper });
    await waitFor(() => expect(hook.result.current.query.data).toEqual(STATE));
    expect(gets).toBe(1);
    return hook;
  }

  test("a save shows at once in the cached state, then refetches", async () => {
    server.use(http.put("/api/v1/projects/42/overview-layout/personal", () => HttpResponse.json(row(1))));
    const hook = await mounted();
    await act(() => hook.result.current.save.mutateAsync({ mode: "personal", layout: A, version: 0 }));
    expect(client.getQueryData(layoutKey(42))).toEqual(afterSave(STATE, "personal", row(1)));
    await waitFor(() => expect(gets).toBe(2));
    release();
  });

  test("a reset shows at once in the cached state, then refetches", async () => {
    server.use(http.delete("/api/v1/projects/42/overview-layout/project", () => new HttpResponse(null, { status: 204 })));
    const hook = await mounted();
    await act(() => hook.result.current.reset.mutateAsync("project"));
    expect(client.getQueryData(layoutKey(42))).toEqual(afterReset(STATE, "project"));
    await waitFor(() => expect(gets).toBe(2));
    release();
  });

  test("a stale save names the stored version and refetches, so Reload or Overwrite starts from it", async () => {
    const current = { version: 9, updated_by: 3, updated_at: "2026-10-11T11:00:00Z" };
    server.use(http.put("/api/v1/projects/42/overview-layout/project", () => HttpResponse.json(
      { detail: { code: "stale_version", message: "The layout changed since you started", current } }, { status: 409 },
    )));
    const hook = await mounted();
    let error: unknown;
    await act(() => hook.result.current.save.mutateAsync({ mode: "project", layout: A, version: 1 }).catch((e: unknown) => {
      error = e;
    }));
    expect(conflictOf(error)).toEqual(current);
    expect(client.getQueryData(layoutKey(42))).toEqual(STATE);
    await waitFor(() => expect(gets).toBe(2));
    release();
  });

  test("another failed save does not refetch", async () => {
    server.use(http.put("/api/v1/projects/42/overview-layout/project", () =>
      HttpResponse.json({ detail: "schema must be 1" }, { status: 422 })));
    const hook = await mounted();
    await act(() => hook.result.current.save.mutateAsync({ mode: "project", layout: A, version: 1 }).catch(() => undefined));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(gets).toBe(1);
  });
});
