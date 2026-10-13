import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import RunsPage from "./RunsPage";

// The live tests poll fast; the others never poll during the test
const live = vi.hoisted(() => ({ ms: 60_000 }));
vi.mock("../lib/live", () => ({ get LIVE_REFRESH_MS() { return live.ms; } }));
afterEach(() => { live.ms = 60_000; });

const run = (id: number) => ({
  id, project_id: 42, ci_provider: "github_actions",
  ci_run_url: "https://ci.example/run/" + id, commit_sha: "abcdef1234567890",
  branch: "main", environment: "ci", agent_version: "0.1.0",
  started_at: "2026-10-01T12:00:00Z", finished_at: "2026-10-01T12:04:00Z",
  duration_ms: 240000, total: 24, passed: 20, failed: 3, skipped: 0, errored: 1,
  created_at: "2026-10-01T12:05:00Z",
});

function Location() {
  const { search } = useLocation();
  return <output data-testid="location">{search}</output>;
}

function renderRuns(url = "/projects/42/runs") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/runs" element={<><RunsPage /><Location /></>} />
          <Route path="/projects/:projectId/runs/:runId" element={<div>RUN DETAIL</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders runs; clicking a run opens its detail", async () => {
  server.use(
    http.get("/api/v1/projects/42/runs", () => HttpResponse.json([run(61)])),
  );
  renderRuns();
  // The page name is the one h1; the org and project live in the breadcrumb
  expect(await screen.findByRole("heading", { level: 1, name: "Runs" })).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("link", { name: /#61/ }));
  expect(await screen.findByText("RUN DETAIL")).toBeInTheDocument();
});

test("branch filter applies on submit; empty state offers to clear", async () => {
  const branches: (string | null)[] = [];
  server.use(
    http.get("/api/v1/projects/42/runs", ({ request }) => {
      branches.push(new URL(request.url).searchParams.get("branch"));
      return HttpResponse.json([]);
    }),
  );
  renderRuns();
  await screen.findByText(/no runs/i);
  const before = branches.length;
  await userEvent.type(screen.getByLabelText(/branch/i), "release");
  expect(branches.length).toBe(before);
  await userEvent.click(screen.getByRole("button", { name: /apply/i }));
  expect(await screen.findByText(/no runs match these filters/i)).toBeInTheDocument();
  expect(branches[branches.length - 1]).toBe("release");
  expect(screen.getByTestId("location")).toHaveTextContent("?branch=release");
});

test("full page enables Next; empty later page keeps Previous reachable", async () => {
  server.use(
    http.get("/api/v1/projects/42/runs", ({ request }) => {
      const offset = Number(new URL(request.url).searchParams.get("offset"));
      return HttpResponse.json(
        offset === 0 ? Array.from({ length: 50 }, (_, i) => run(i + 1)) : [],
      );
    }),
  );
  renderRuns();
  await screen.findByRole("link", { name: /#1\b/ });
  await userEvent.click(screen.getByRole("button", { name: /next/i }));
  await screen.findByText(/no runs/i);
  await userEvent.click(screen.getByRole("button", { name: /previous/i }));
  expect(await screen.findByRole("link", { name: /#1\b/ })).toBeInTheDocument();
});

function captureQueries() {
  const seen: URLSearchParams[] = [];
  server.use(
    http.get("/api/v1/projects/42/runs", ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json([]);
    }),
  );
  return seen;
}

test("filters in the URL drive the first request and prefill the form", async () => {
  const seen = captureQueries();
  renderRuns("/projects/42/runs?status=failing&environment=qa&author=ana");
  await screen.findByText(/no runs match these filters/i);
  const q = seen[seen.length - 1];
  expect(q.get("status")).toBe("failing");
  expect(q.get("environment")).toBe("qa");
  expect(q.get("author")).toBe("ana");
  expect(screen.getByLabelText(/^status/i)).toHaveValue("failing");
  // An active advanced filter keeps "More filters" open
  expect(screen.getByLabelText(/^environment/i)).toBeVisible();
  expect(screen.getByLabelText(/^author/i)).toHaveValue("ana");
});

test("more filters send commit, PR, CI and a local date range", async () => {
  const seen = captureQueries();
  renderRuns();
  await screen.findByText(/no runs yet/i);
  await userEvent.click(screen.getByText(/more filters/i));
  await userEvent.type(screen.getByLabelText(/commit/i), "abc12");
  await userEvent.type(screen.getByLabelText(/pull request/i), "42");
  await userEvent.selectOptions(screen.getByLabelText(/^ci$/i), "azure_pipelines");
  await userEvent.type(screen.getByLabelText(/^from/i), "2026-10-01");
  await userEvent.type(screen.getByLabelText(/^to/i), "2026-10-03");
  await userEvent.click(screen.getByRole("button", { name: /apply/i }));
  await screen.findByText(/no runs match these filters/i);
  const q = seen[seen.length - 1];
  expect(q.get("commit")).toBe("abc12");
  expect(q.get("pr")).toBe("42");
  expect(q.get("ci_provider")).toBe("azure_pipelines");
  // Whole local days: from midnight on the 1st to midnight after the 3rd
  expect(q.get("since")).toBe(new Date(2026, 9, 1).toISOString());
  expect(q.get("until")).toBe(new Date(2026, 9, 4).toISOString());
  expect(screen.getByTestId("location")).toHaveTextContent("from=2026-10-01");
});

test("Clear all drops every filter and refetches; the form has no second clear button", async () => {
  const seen = captureQueries();
  renderRuns("/projects/42/runs?status=passing&branch=main&environment=qa&author=ana&from=2026-10-01");
  await screen.findByRole("button", { name: "Clear all" });
  expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
  await screen.findByText(/no runs yet/i);
  const q = seen[seen.length - 1];
  expect([...q.keys()].sort()).toEqual(["limit", "offset"]);
  expect(screen.getByTestId("location")).toBeEmptyDOMElement();
  expect(screen.getByLabelText(/branch/i)).toHaveValue("");
});

test("first page refreshes on its own and announces new runs", async () => {
  live.ms = 60;
  let calls = 0;
  server.use(
    http.get("/api/v1/projects/42/runs", () => {
      calls += 1;
      return HttpResponse.json(calls === 1 ? [run(1)] : [run(3), run(2), run(1)]);
    }),
  );
  renderRuns();
  await screen.findByRole("link", { name: /#1\b/ });
  expect(await screen.findByRole("link", { name: /#3\b/ })).toBeInTheDocument();
  expect(await screen.findByText("2 new runs")).toHaveAttribute("role", "status");
});

test("later pages do not refresh on their own", async () => {
  live.ms = 60;
  let calls = 0;
  server.use(
    http.get("/api/v1/projects/42/runs", ({ request }) => {
      const offset = Number(new URL(request.url).searchParams.get("offset"));
      if (offset > 0) calls += 1;
      return HttpResponse.json(offset === 0 ? Array.from({ length: 50 }, (_, i) => run(i + 1)) : [run(99)]);
    }),
  );
  renderRuns();
  await screen.findByRole("link", { name: /#1\b/ });
  await userEvent.click(screen.getByRole("button", { name: /next/i }));
  await screen.findByRole("link", { name: /#99/ });
  await new Promise((r) => setTimeout(r, 300));
  expect(calls).toBe(1);
});

test("columns hidden on phones come back as a second line in the Run cell", async () => {
  server.use(http.get("/api/v1/projects/42/runs", () => HttpResponse.json([run(61)])));
  renderRuns();
  const link = await screen.findByRole("link", { name: /#61/ });
  const cell = link.closest("td")!;
  const meta = cell.querySelector(".narrow-meta")!;
  expect(meta).toBeInTheDocument();
  expect(meta).toHaveTextContent("Commit abcdef1");
  expect(meta).toHaveTextContent("Environment ci");
  expect(meta).toHaveTextContent("CI GitHub Actions");
  expect(meta).toHaveTextContent("Errored 1");
  expect(meta).toHaveTextContent("Skipped 0");
  expect(meta).toHaveTextContent("Duration");
});

test("a Status column names each run's verdict with an icon and a word", async () => {
  server.use(
    http.get("/api/v1/projects/42/runs", () =>
      HttpResponse.json([
        { ...run(3), failed: 0, errored: 0 },
        { ...run(2), failed: 0, errored: 2 },
        { ...run(1), failed: 4 },
      ]),
    ),
  );
  renderRuns();
  await screen.findByRole("link", { name: "#3" });
  expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
  // Wide cells and the narrow-meta line each carry it; the table body has one pill per run per place
  expect(screen.getAllByText("Passed", { selector: ".pill" }).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Errored", { selector: ".pill" }).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Failed", { selector: ".pill" }).length).toBeGreaterThan(0);
  const cells = screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td.hide-narrow")?.textContent?.trim());
  expect(cells).toEqual(["Passed", "Errored", "Failed"]);
  // Narrow screens: the same verdict leads the muted line under the run link
  const firstRow = screen.getAllByRole("row")[1];
  expect(firstRow.querySelector(".narrow-meta")).toHaveTextContent("Status Passed");
});

test("column headers sort the loaded page and keep the order in the URL", async () => {
  server.use(
    http.get("/api/v1/projects/42/runs", () =>
      HttpResponse.json([
        { ...run(1), failed: 2, duration_ms: 5000, started_at: "2026-10-01T10:00:00Z" },
        { ...run(2), failed: 9, duration_ms: 1000, started_at: "2026-10-02T10:00:00Z" },
        { ...run(3), failed: 0, duration_ms: 9000, started_at: "2026-10-03T10:00:00Z" },
      ]),
    ),
  );
  renderRuns();
  const ids = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("a")?.textContent);
  await screen.findByRole("link", { name: "#3" });
  // Default: newest first
  expect(ids()).toEqual(["#3", "#2", "#1"]);
  expect(screen.getByRole("columnheader", { name: /started/i })).toHaveAttribute("aria-sort", "descending");
  expect(screen.getByRole("columnheader", { name: /^failed/i })).not.toHaveAttribute("aria-sort");

  await userEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /^failed/i }));
  expect(ids()).toEqual(["#2", "#1", "#3"]);
  expect(screen.getByRole("columnheader", { name: /^failed/i })).toHaveAttribute("aria-sort", "descending");
  expect(screen.getByRole("columnheader", { name: /started/i })).not.toHaveAttribute("aria-sort");
  expect(screen.getByTestId("location")).toHaveTextContent("sort=failed");

  await userEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /^failed/i }));
  expect(ids()).toEqual(["#3", "#1", "#2"]);
  expect(screen.getByRole("columnheader", { name: /^failed/i })).toHaveAttribute("aria-sort", "ascending");
  expect(screen.getByTestId("location")).toHaveTextContent("dir=asc");

  await userEvent.click(screen.getByRole("button", { name: /duration/i }));
  expect(ids()).toEqual(["#3", "#1", "#2"]);
});

test("a shared sorted link opens sorted", async () => {
  server.use(
    http.get("/api/v1/projects/42/runs", () =>
      HttpResponse.json([{ ...run(1), duration_ms: 100 }, { ...run(2), duration_ms: 900 }]),
    ),
  );
  renderRuns("/projects/42/runs?sort=duration&dir=asc");
  await screen.findByRole("link", { name: "#1" });
  expect(screen.getAllByRole("row").slice(1).map((r) => r.querySelector("a")?.textContent)).toEqual(["#1", "#2"]);
  expect(screen.getByRole("columnheader", { name: /duration/i })).toHaveAttribute("aria-sort", "ascending");
});

const subsetRun = (id: number) => ({
  ...run(id), scope: "impact-subset",
  stages: { stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }], time_to_first_failure_s: 30, stopped_after_stage: 1 },
});

test("a suggested-only run carries a pill, and Full runs only asks the server to leave them out", async () => {
  const scopes: (string | null)[] = [];
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    const scope = new URL(request.url).searchParams.get("scope");
    scopes.push(scope);
    return HttpResponse.json(scope === "full" ? [run(61)] : [subsetRun(62), run(61)]);
  }));
  renderRuns();
  const row = (await screen.findByRole("link", { name: "#62" })).closest("tr")!;
  expect(within(row).getByText("Suggested only · stopped after stage 1")).toBeInTheDocument();
  expect(within(screen.getByRole("link", { name: "#61" }).closest("tr")!).queryByText(/Suggested only/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Full runs only" }));
  await waitFor(() => expect(screen.queryByRole("link", { name: "#62" })).not.toBeInTheDocument());
  expect(scopes[scopes.length - 1]).toBe("full");
  expect(screen.getByTestId("location")).toHaveTextContent("scope=full");
});

test("the Runs filter names the applied scope", async () => {
  server.use(http.get("/api/v1/projects/42/runs", () => HttpResponse.json([])));
  renderRuns("/projects/42/runs?scope=impact-subset");
  expect(await screen.findByText("Runs: Suggested tests only")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Full runs only" })).toHaveAttribute("aria-pressed", "false");
});
