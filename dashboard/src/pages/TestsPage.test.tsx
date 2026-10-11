import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { downloadCsv } from "../lib/csv";
import TestsPage from "./TestsPage";

vi.mock("../lib/csv", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/csv")>()),
  downloadCsv: vi.fn(),
}));

const row = (key: string, name: string) => ({
  test_key: key, suite: "auth", class_name: "TestLogin", name,
  runs: 10, passed: 9, failed: 1, errored: 0, skipped: 0,
  pass_rate: 0.9, avg_duration_ms: 420, last_status: "failed", last_seen: "2026-09-30T10:00:00Z",
});

function renderTests() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/tests"]}>
        <Routes>
          <Route path="/projects/:projectId/tests" element={<TestsPage />} />
          <Route path="/projects/:projectId/tests/:testKey" element={<div>HISTORY</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders rows; clicking a test navigates to its encoded history route", async () => {
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", () =>
      HttpResponse.json([row("tests/a.py::TestLogin::test_ok", "test_ok")]),
    ),
  );
  renderTests();
  // The page name is the one h1; the org and project live in the breadcrumb
  expect(await screen.findByRole("heading", { level: 1, name: "Test results" })).toBeInTheDocument();
  await userEvent.click(await screen.findByText("test_ok"));
  expect(await screen.findByText("HISTORY")).toBeInTheDocument();
});

test("search and sort map to params; next page advances offset", async () => {
  const calls: URLSearchParams[] = [];
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", ({ request }) => {
      calls.push(new URL(request.url).searchParams);
      // One row more than the page size signals that "Next" should be enabled.
      return HttpResponse.json(Array.from({ length: 51 }, (_, i) => row(`k${i}`, `t${i}`)));
    }),
  );
  renderTests();
  await screen.findByText("t0");
  await userEvent.click(screen.getByRole("button", { name: /avg duration/i }));
  await userEvent.type(screen.getByLabelText(/search/i), "login");
  await userEvent.click(screen.getByRole("button", { name: /apply/i }));
  await userEvent.click(await screen.findByRole("button", { name: /next/i }));
  const last = calls[calls.length - 1];
  expect(last.get("sort")).toBe("duration");
  expect(last.get("search")).toBe("login");
  expect(last.get("offset")).toBe("50");
});

test("empty page past the first keeps Previous reachable", async () => {
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", ({ request }) => {
      const offset = Number(new URL(request.url).searchParams.get("offset"));
      // The first page claims another one follows, but it comes back empty (rows deleted meanwhile).
      return HttpResponse.json(
        offset === 0 ? Array.from({ length: 51 }, (_, i) => row(`k${i}`, `t${i}`)) : [],
      );
    }),
  );
  renderTests();
  await screen.findByText("t0");
  await userEvent.click(screen.getByRole("button", { name: /next/i }));
  await screen.findByText(/no tests/i);
  await userEvent.click(screen.getByRole("button", { name: /previous/i }));
  expect(await screen.findByText("t0")).toBeInTheDocument();
});

test("Export CSV downloads the full filtered dataset", async () => {
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", ({ request }) => {
      const params = new URL(request.url).searchParams;
      // The export pager asks with limit=200; the view itself uses 50.
      if (params.get("limit") === "200") {
        return HttpResponse.json([row("k1", "t1"), row("k2", "t2")]);
      }
      return HttpResponse.json([row("k1", "t1")]);
    }),
  );
  renderTests();
  await screen.findByText("t1");
  await userEvent.click(screen.getByRole("button", { name: /export csv/i }));
  await vi.waitFor(() => expect(downloadCsv).toHaveBeenCalled());
  const [filename, csv] = vi.mocked(downloadCsv).mock.calls[0];
  expect(filename).toMatch(/tests-project-42.*\.csv/);
  expect(csv.split("\r\n")).toHaveLength(3); // header + 2 rows
  expect(csv).toContain("test_key");
  expect(csv).toContain("k2");
});

test("empty result shows an empty state", async () => {
  server.use(http.get("/api/v1/projects/42/analytics/tests", () => HttpResponse.json([])));
  renderTests();
  expect(await screen.findByText(/no tests/i)).toBeInTheDocument();
});

test("runs, errored, average duration and last seen are in the Test cell for phones", async () => {
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", () => HttpResponse.json([row("k1", "test_ok")])),
  );
  renderTests();
  const meta = (await screen.findByRole("link", { name: "test_ok" })).closest("td")!.querySelector(".narrow-meta")!;
  expect(meta).toHaveTextContent("Runs 10");
  expect(meta).toHaveTextContent("Errored 0");
  expect(meta).toHaveTextContent("Avg duration");
  expect(meta).toHaveTextContent("Last seen");
});

test("headers sort: failures, duration and name go to the server; the rest order the loaded rows", async () => {
  const sorts: (string | null)[] = [];
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", ({ request }) => {
      sorts.push(new URL(request.url).searchParams.get("sort"));
      return HttpResponse.json([
        { ...row("a", "alpha"), pass_rate: 0.5, last_seen: "2026-09-01T10:00:00Z" },
        { ...row("b", "bravo"), pass_rate: 0.9, last_seen: "2026-09-03T10:00:00Z" },
        { ...row("c", "charlie"), pass_rate: 0.1, last_seen: "2026-09-02T10:00:00Z" },
      ]);
    }),
  );
  renderTests();
  await screen.findByText("alpha");
  const names = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("a")?.textContent);
  expect(screen.getByRole("columnheader", { name: /^failed/i })).toHaveAttribute("aria-sort", "descending");
  expect(sorts[sorts.length - 1]).toBe("failures");

  await userEvent.click(screen.getByRole("button", { name: /^test/i }));
  await waitFor(() => expect(sorts[sorts.length - 1]).toBe("name"));
  expect(screen.getByRole("columnheader", { name: /^test/i })).toHaveAttribute("aria-sort", "ascending");

  // Pass rate is not a server sort: the request keeps ordering by failures, the page reorders itself
  await userEvent.click(screen.getByRole("button", { name: /pass rate/i }));
  await waitFor(() => expect(names()).toEqual(["bravo", "alpha", "charlie"]));
  expect(sorts[sorts.length - 1]).toBe("failures");
  expect(screen.getByText(/sorted within these 3 rows/i)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /last seen/i }));
  expect(names()).toEqual(["bravo", "charlie", "alpha"]);
});
