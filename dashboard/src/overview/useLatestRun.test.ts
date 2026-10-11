import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { newRunStaleKeys } from "./queries";
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
