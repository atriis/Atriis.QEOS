import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { REGISTRY, newRunStaleKeys } from "./widgets/registry";
import { useLatestRun } from "./useLatestRun";

test("a new latest run refreshes the non-polled figures once; the first load and an unchanged run do not", async () => {
  setAccessToken("acc");
  let runId = 1;
  server.use(http.get("/api/v1/projects/42/runs", () =>
    HttpResponse.json([{ id: runId, project_id: 42, passed: 3, failed: 0, errored: 0 }])));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  const { result } = renderHook(() => useLatestRun(42), { wrapper });

  await waitFor(() => expect(result.current.latest?.id).toBe(1));
  await act(() => result.current.runs.refetch());
  expect(invalidate).not.toHaveBeenCalled();

  runId = 2;
  await act(() => result.current.runs.refetch());
  await waitFor(() => expect(result.current.latest?.id).toBe(2));
  expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual(newRunStaleKeys(42));
});

test("a new latest run invalidates each registered widget's own keys, and the page's", async () => {
  setAccessToken("acc");
  let runId = 1;
  server.use(http.get("/api/v1/projects/42/runs", () =>
    HttpResponse.json([{ id: runId, project_id: 42, passed: 3, failed: 0, errored: 0 }])));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const widgetKeys = Object.values(REGISTRY).flatMap((def) => def.staleKeys?.(42) ?? []);
  expect(widgetKeys).toContainEqual(["trends", 42]);
  // A cached answer under each widget key (with filters after it, as the widgets ask)
  const cached = widgetKeys.map((key) => [...key, "with-filters"]);
  for (const key of cached) client.setQueryData(key, { cached: true });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  const { result } = renderHook(() => useLatestRun(42), { wrapper });
  await waitFor(() => expect(result.current.latest?.id).toBe(1));
  for (const key of cached) expect(client.getQueryState(key)?.isInvalidated).toBe(false);

  runId = 2;
  await act(() => result.current.runs.refetch());
  await waitFor(() => expect(result.current.latest?.id).toBe(2));
  for (const key of cached) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
});

test("the keys a new run makes stale name each query once: a key a broader one already covers is left out", () => {
  const keys = newRunStaleKeys(42);
  for (const [i, key] of keys.entries()) {
    for (const [j, other] of keys.entries()) {
      if (i !== j) expect(other.length <= key.length && other.every((part, n) => part === key[n])).toBe(false);
    }
  }
  // Today's page-level keys stay, in order
  expect(keys.slice(0, 5)).toEqual([["trends", 42], ["flaky", 42], ["report", 42], ["branches", 42], ["latest-keys", 42]]);
});

test("a widget key the page's keys do not cover is kept and invalidated by a new run", async () => {
  setAccessToken("acc");
  let runId = 1;
  server.use(http.get("/api/v1/projects/42/runs", () =>
    HttpResponse.json([{ id: runId, project_id: 42, passed: 3, failed: 0, errored: 0 }])));
  const def = REGISTRY.latest_run!;
  def.staleKeys = (projectId) => [["widget-only", projectId]];
  try {
    expect(newRunStaleKeys(42)).toContainEqual(["widget-only", 42]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["widget-only", 42, "filters"], { cached: true });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const { result } = renderHook(() => useLatestRun(42), { wrapper });
    await waitFor(() => expect(result.current.latest?.id).toBe(1));
    expect(client.getQueryState(["widget-only", 42, "filters"])?.isInvalidated).toBe(false);
    runId = 2;
    await act(() => result.current.runs.refetch());
    await waitFor(() => expect(result.current.latest?.id).toBe(2));
    expect(client.getQueryState(["widget-only", 42, "filters"])?.isInvalidated).toBe(true);
  } finally {
    delete def.staleKeys;
  }
});
