import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import RunDetailPage from "./RunDetailPage";

const detail = (results: object[]) => ({
  id: 61, project_id: 42, ci_provider: "github_actions",
  ci_run_url: "https://ci.example/run/61", commit_sha: "abcdef1234567890",
  branch: "main", environment: "ci", agent_version: "0.1.0",
  started_at: "2026-10-01T12:00:00Z", finished_at: "2026-10-01T12:04:00Z",
  duration_ms: 240000, total: 24, passed: 20, failed: 3, skipped: 0, errored: 1,
  created_at: "2026-10-01T12:05:00Z",
  commit_author: null, commit_message: null, pr_number: null, base_branch: null,
  change_base_ref: null, changed_files: null, additions: null, deletions: null,
  changes_truncated: null, changes: [], components: [], results,
});

const result = {
  id: 1, test_key: "tests/a.py::TestLogin::test_ok", suite: "auth",
  class_name: "TestLogin", name: "test_ok", status: "failed", duration_ms: 480,
  message: "AssertionError: boom", details: null, truncated: true, redacted: false,
  file: "tests/a.py", owner: null,
};

function Where() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{pathname + search}</output>;
}

function renderDetail(url = "/projects/42/runs/61") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/runs/:runId" element={<><RunDetailPage /><Where /></>} />
          <Route path="/projects/:projectId/tests/:testKey" element={<div>HISTORY</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders run metadata, truncated badge, and links to test history", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([result]))));
  renderDetail();
  // The page name is the one h1; the org and project live in the breadcrumb
  expect(await screen.findByRole("heading", { level: 1, name: "Run #61" })).toBeInTheDocument();
  expect(await screen.findByText("abcdef1")).toBeInTheDocument();
  expect(screen.getByText(/truncated/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "test_ok" }));
  expect(await screen.findByText("HISTORY")).toBeInTheDocument();
});

test("status filter refetches server-side", async () => {
  const statuses: (string | null)[] = [];
  server.use(
    http.get("/api/v1/runs/61", ({ request }) => {
      statuses.push(new URL(request.url).searchParams.get("status"));
      return HttpResponse.json(detail([]));
    }),
  );
  renderDetail();
  await screen.findByText(/no results/i);
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "failed");
  await screen.findByText(/no failed results/i);
  expect(statuses[statuses.length - 1]).toBe("failed");
  expect(statuses[0]).toBeNull();
});


test("a run with change data shows the Changes card and file list", async () => {
  const withChanges = {
    ...detail([]),
    change_base_ref: "origin/main", changed_files: 2, additions: 12, deletions: 3,
    changes_truncated: true,
    changes: [
      { path: "src/app.py", status: "M", additions: 12, deletions: 3 },
      { path: "assets/logo.png", status: "A", additions: null, deletions: null },
    ],
  };
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(withChanges)));
  renderDetail();
  expect(await screen.findByText("src/app.py")).toBeInTheDocument();
  expect(screen.getByText(/\+12\s*−3 vs origin\/main/)).toBeInTheDocument();
  expect(screen.getByText(/list truncated/i)).toBeInTheDocument();
});

test("a run without change data shows no Changes card", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([]))));
  renderDetail();
  await screen.findByText(/run #61/i);
  expect(screen.queryByText(/changes/i)).not.toBeInTheDocument();
});


test("a result's owner renders when present", async () => {
  const owned = { ...result, owner: "@org/qa-team" };
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([owned]))));
  renderDetail();
  expect(await screen.findByText(/@org\/qa-team/)).toBeInTheDocument();
});

test("components under test render when present", async () => {
  const withComponents = {
    ...detail([]),
    components: [
      { name: "product-api", sha: "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" },
      { name: "web-frontend", sha: "0f1e2d3c" },
    ],
  };
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(withComponents)));
  renderDetail();
  expect(await screen.findByText(/under test/i)).toBeInTheDocument();
  expect(screen.getByText(/product-api@a1b2c3d4e5f6/)).toBeInTheDocument();
  expect(screen.getByText(/web-frontend@0f1e2d3c/)).toBeInTheDocument();
});

test("no components line when the run reported none", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([]))));
  renderDetail();
  await screen.findByText(/run #61/i);
  expect(screen.queryByText(/under test/i)).not.toBeInTheDocument();
});


test("git metadata renders when present", async () => {
  const withMeta = {
    ...detail([]),
    commit_author: "Ada Lovelace",
    commit_message: "fix(cart): keep totals stable",
    pr_number: 123,
    base_branch: "main",
  };
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(withMeta)));
  renderDetail();
  expect(await screen.findByText(/Ada Lovelace/)).toBeInTheDocument();
  expect(screen.getByText(/fix\(cart\): keep totals stable/)).toBeInTheDocument();
  expect(screen.getByText(/PR #123/)).toBeInTheDocument();
});

test("failures are grouped by cause, each group lists its tests", async () => {
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json(detail([result]))),
    http.get("/api/v1/runs/61/failure-groups", () => HttpResponse.json({
      total: 4,
      groups: [
        { signature: "a1", headline: "TimeoutError: waiting for locator('#pay')", count: 3, failed: 2, errored: 1, history: { window: 10, seen_in: 6, streak: 4, since_run_id: 57, since_started_at: "2026-09-28T12:00:00Z" },
          tests: [
            { id: 1, test_key: "k1", suite: "checkout", class_name: "Cart", name: "pays by card", status: "failed" },
            { id: 2, test_key: "k2", suite: "checkout", class_name: "Cart", name: "pays by voucher", status: "failed" },
            { id: 3, test_key: "k3", suite: "checkout", class_name: "Cart", name: "pays later", status: "errored" },
          ] },
        { signature: "none", headline: null, count: 1, failed: 1, errored: 0, history: { window: 10, seen_in: 1, streak: 1, since_run_id: 61, since_started_at: "2026-10-01T12:00:00Z" },
          tests: [{ id: 4, test_key: "k4", suite: "auth", class_name: "Login", name: "logs in", status: "failed" }] },
      ],
    })),
  );
  renderDetail();
  expect(await screen.findByRole("heading", { name: /failures by cause/i })).toBeInTheDocument();
  expect(await screen.findByText("TimeoutError: waiting for locator('#pay')")).toBeInTheDocument();
  expect(screen.getByText(/no error message/i)).toBeInTheDocument();
  expect(screen.getByText(/4 failures, 2 causes/i)).toBeInTheDocument();
  // how long each cause has been around on this branch
  expect(screen.getByText(/in the last 4 runs, since #57/i)).toBeInTheDocument();
  expect(screen.getByText(/6 of the last 10 runs/i)).toBeInTheDocument();
  expect(screen.getByText(/new in this run/i)).toBeInTheDocument();
  await userEvent.click(screen.getByText(/3 tests/));
  expect(screen.getByRole("link", { name: "pays later" })).toHaveAttribute("href", "/projects/42/tests/k3");
});

test("a green run shows no cause section", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json({ ...detail([]), failed: 0, errored: 0 })));
  renderDetail();
  await screen.findByText("abcdef1");
  expect(screen.queryByRole("heading", { name: /failures by cause/i })).not.toBeInTheDocument();
});

test("links to a comparison with the previous run on the branch", async () => {
  let until: string | null = null;
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json(detail([result]))),
    http.get("/api/v1/projects/42/runs", ({ request }) => {
      const q = new URL(request.url).searchParams;
      until = q.get("until");
      return HttpResponse.json(q.get("branch") === "main" ? [{ ...detail([]), id: 58 }] : []);
    }),
  );
  renderDetail();
  const link = await screen.findByRole("link", { name: /compare with previous run #58/i });
  expect(link).toHaveAttribute("href", "/projects/42/runs/61/compare/58");
  expect(until).toBe("2026-10-01T12:00:00Z");
});

test("quarantined failures are marked and kept out of the failing count", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json({
    ...detail([{ ...result, quarantined: true }, { ...result, id: 2, name: "test_real", quarantined: false }]),
    quarantined: 1, blocking: 3,
  })));
  renderDetail();
  expect(await screen.findByText(/1 in quarantine, not counted/i)).toBeInTheDocument();
  expect(screen.getByText("Failing")).toBeInTheDocument();
  const row = screen.getByRole("link", { name: "test_ok" }).closest("tr")!;
  expect(row).toHaveTextContent(/quarantined/i);
  expect(screen.getByRole("link", { name: "test_real" }).closest("tr")).not.toHaveTextContent(/quarantined/i);
});

test("the status filter lives in the URL", async () => {
  const statuses: (string | null)[] = [];
  server.use(http.get("/api/v1/runs/61", ({ request }) => {
    statuses.push(new URL(request.url).searchParams.get("status"));
    return HttpResponse.json(detail([]));
  }));
  renderDetail("/projects/42/runs/61?status=errored");
  await screen.findByText(/no errored results/i);
  expect(statuses[0]).toBe("errored");
  expect(screen.getByLabelText(/status/i)).toHaveValue("errored");
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "");
  expect(screen.getByTestId("where").textContent).toBe("/projects/42/runs/61");
});

test("changing the filter keeps the page and the focused select mounted", async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => { release = r; });
  server.use(http.get("/api/v1/runs/61", async ({ request }) => {
    if (new URL(request.url).searchParams.get("status") === "failed") await gate;
    return HttpResponse.json(detail([result]));
  }));
  renderDetail();
  await screen.findByText("test_ok");
  const select = screen.getByLabelText(/status/i);
  await userEvent.selectOptions(select, "failed");
  // still the same element, still focused, previous rows still shown, with a hint that it is refreshing
  expect(screen.getByLabelText(/status/i)).toBe(select);
  expect(select).toHaveFocus();
  expect(screen.getByText("test_ok")).toBeInTheDocument();
  expect(screen.getByText(/updating results/i)).toBeInTheDocument();
  release();
  await waitFor(() => expect(screen.queryByText(/updating results/i)).not.toBeInTheDocument());
  expect(select).toHaveFocus();
});

const many = (n: number) => Array.from({ length: n }, (_, i) => ({
  ...result, id: i + 1, test_key: `k${i + 1}`, name: `t${i + 1}`,
  // The last ten fail: they must lead the first page
  status: i >= n - 10 ? "failed" : "passed", message: null,
}));

test("thousands of results are paged 100 at a time, failing first, with the page in the URL", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(250)))));
  renderDetail();
  const region = await screen.findByRole("region", { name: "Test results" });
  expect(within(region).getAllByRole("row")).toHaveLength(101); // header + 100
  const first = within(region).getAllByRole("row")[1];
  expect(within(first).getByRole("link", { name: "t241" })).toBeInTheDocument(); // a failed one leads
  expect(within(region).getByText("Rows 1–100 of 250")).toBeInTheDocument();
  expect(within(region).getByRole("button", { name: "Previous" })).toBeDisabled();

  await userEvent.click(within(region).getByRole("button", { name: "Next" }));
  expect(screen.getByTestId("where")).toHaveTextContent("?offset=100");
  expect(within(region).getByText("Rows 101–200 of 250")).toBeInTheDocument();
  await userEvent.click(within(region).getByRole("button", { name: "Next" }));
  expect(within(region).getAllByRole("row")).toHaveLength(51);
  expect(within(region).getByRole("button", { name: "Next" })).toBeDisabled();
});

test("a pasted page link opens that page, and changing the status filter returns to page 1", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(250)))));
  renderDetail("/projects/42/runs/61?offset=200");
  const region = await screen.findByRole("region", { name: "Test results" });
  expect(within(region).getByText("Rows 201–250 of 250")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "passed");
  expect(screen.getByTestId("where")).not.toHaveTextContent("offset");
});

test("a short run shows no pager", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(5)))));
  renderDetail();
  const region = await screen.findByRole("region", { name: "Test results" });
  expect(within(region).queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
});

test("a hand-edited offset is rounded down to a page boundary; one past the end shows the last page", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(250)))));
  renderDetail("/projects/42/runs/61?offset=150");
  const region = await screen.findByRole("region", { name: "Test results" });
  expect(within(region).getByText("Rows 101–200 of 250")).toBeInTheDocument();
});

test("an offset beyond the results shows the last page, and Previous goes back one page", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(250)))));
  renderDetail("/projects/42/runs/61?offset=99999");
  const region = await screen.findByRole("region", { name: "Test results" });
  expect(within(region).getByText("Rows 201–250 of 250")).toBeInTheDocument();
  await userEvent.click(within(region).getByRole("button", { name: "Previous" }));
  expect(within(region).getByText("Rows 101–200 of 250")).toBeInTheDocument();
});

test("junk offsets read as the first page", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(250)))));
  renderDetail("/projects/42/runs/61?offset=-5");
  const region = await screen.findByRole("region", { name: "Test results" });
  expect(within(region).getByText("Rows 1–100 of 250")).toBeInTheDocument();
});

test("results are ordered failed, errored, other, skipped, passed", async () => {
  const mk = (id: number, status: string) => ({ ...result, id, test_key: `k${id}`, name: `t-${status}`, status, message: null });
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([
    mk(1, "passed"), mk(2, "skipped"), mk(3, "weird"), mk(4, "errored"), mk(5, "failed"),
  ]))));
  renderDetail();
  const region = await screen.findByRole("region", { name: "Test results" });
  const names = within(region).getAllByRole("row").slice(1).map((r) => within(r).getByRole("link").textContent);
  expect(names).toEqual(["t-failed", "t-errored", "t-weird", "t-skipped", "t-passed"]);
});

test("changing page scrolls to the top of the table", async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  try {
    server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail(many(250)))));
    renderDetail();
    const region = await screen.findByRole("region", { name: "Test results" });
    expect(scroll).not.toHaveBeenCalled(); // not on the first render
    await userEvent.click(within(region).getByRole("button", { name: "Next" }));
    expect(scroll).toHaveBeenCalledWith({ block: "start" });
  } finally {
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  }
});

test("a run that reported changes shows its likely affected tests beside them", async () => {
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json({
      ...detail([result]), change_base_ref: "origin/main", changed_files: 1, additions: 3, deletions: 1, changes_truncated: false,
      changes: [{ path: "src/payment/api.py", status: "M", additions: 3, deletions: 1 }],
    })),
    http.get("/api/v1/projects/42/runs/61/impact", () => HttpResponse.json({
      run_id: 61, state: "not_scored", changed_paths: ["src/payment/api.py"], replayed: false, scored_at: null,
      suggestion: null, outcome: null })),
  );
  renderDetail();
  expect(await screen.findByRole("heading", { name: "Changes" })).toBeInTheDocument();
  const region = await screen.findByRole("region", { name: "Likely affected tests" });
  expect(await within(region).findByText(/No suggestion was stored for this run/)).toBeInTheDocument();
});

test("a run that reported no changes says so in its likely affected tests card", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([result]))));
  renderDetail();
  const region = await screen.findByRole("region", { name: "Likely affected tests" });
  expect(await within(region).findByText("No change data for this run")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Changes" })).not.toBeInTheDocument();
});

test("a run-impact run says how its stages went", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json({
    ...detail([]), scope: "full",
    stages: { stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }, { name: "rest", duration_s: 850, tests: 340, failed: 0 }],
      time_to_first_failure_s: 42.5, stopped_after_stage: null },
  })));
  renderDetail();
  expect(await screen.findByText("Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) 340 tests"
    + " in 14m 10s · first failure after 42.5 s (full suite 15m 15s)")).toBeInTheDocument();
  expect(screen.queryByText("Suggested only", { selector: ".pill" })).not.toBeInTheDocument();
});

test("a suggested-only run says so, with a word as well as the line", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json({
    ...detail([]), scope: "impact-subset",
    stages: { stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }], time_to_first_failure_s: 30, stopped_after_stage: 1 },
  })));
  renderDetail();
  expect(await screen.findByText(
    "Suggested tests only, stopped after stage 1: stage 1 (suggested) 12 tests in 1m 05s · first failure after 30.0 s")).toBeInTheDocument();
  expect(screen.getByText("Suggested only", { selector: ".pill" })).toBeInTheDocument();
});

test("an ordinary upload has no stages line", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([]))));
  renderDetail();
  await screen.findByText("abcdef1");
  expect(screen.queryByText(/^Suggested tests/)).not.toBeInTheDocument();
});

test("each row offers the result's log, fetched only when opened", async () => {
  let fetched = 0;
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json(detail([result]))),
    http.get("/api/v1/projects/42/runs/61/results/1/log", () => {
      fetched++;
      return HttpResponse.json({ log: "INFO boom happened", values: [] });
    }),
  );
  renderDetail();
  const button = await screen.findByRole("button", { name: "Log of test_ok" });
  expect(fetched).toBe(0);
  await userEvent.click(button);
  expect(await screen.findByText("INFO boom happened")).toBeInTheDocument();
  expect(fetched).toBe(1);
});

test("with ?value the rows are the results holding it, under a note with a way back to all", async () => {
  const seen: string[] = [];
  server.use(http.get("/api/v1/runs/61", ({ request }) => {
    const q = new URL(request.url).searchParams;
    seen.push(`${q.get("value")}|${q.get("pattern")}`);
    return HttpResponse.json(detail(q.get("value") ? [result] : [result, { ...result, id: 2, name: "test_other" }]));
  }));
  renderDetail("/projects/42/runs/61?value=3960562&pattern=trip_id");
  expect(await screen.findByText("1 of 24 results hold trip_id 3960562")).toBeInTheDocument();
  await waitFor(() => expect(seen).toContain("3960562|trip_id"));
  expect(screen.queryByText("test_other")).toBeNull();
  await userEvent.click(screen.getByRole("link", { name: "Show all results" }));
  expect(await screen.findByText("test_other")).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/runs/61");
});

test("a value no result holds says so, once, with the way back", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([]))));
  renderDetail("/projects/42/runs/61?value=nothing");
  expect(await screen.findByText("No results in this run hold nothing.")).toBeInTheDocument();
  expect(screen.queryByText("No results in this run.")).toBeNull();
  expect(screen.getByRole("link", { name: "Show all results" })).toBeInTheDocument();
});

test("a result with screenshots shows a camera count beside its log; one without shows none", async () => {
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json(detail([
      { ...result, screenshot_count: 3 },
      { ...result, id: 2, test_key: "tests/a.py::TestLogin::test_no", name: "test_no", screenshot_count: 0 },
    ]))),
    http.get("/api/v1/projects/42/runs/61/results/1/screenshots", () => HttpResponse.json({ screenshots: [] })),
  );
  renderDetail();
  const button = await screen.findByRole("button", { name: "Screenshots of test_ok (3)" });
  expect(button).toHaveTextContent("3");
  expect(screen.queryByRole("button", { name: /^Screenshots of test_no/ })).toBeNull();
  await userEvent.click(button);
  expect(await screen.findByRole("dialog", { name: /Screenshots — test_ok/ })).toBeInTheDocument();
});

test("a result with traces has a Trace button and a note; one without has none", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([
    { ...result, trace_count: 1 },
    { ...result, id: 2, test_key: "tests/a.py::TestLogin::test_no", name: "test_no", trace_count: 0 },
    { ...result, id: 3, test_key: "tests/a.py::TestLogin::test_old", name: "test_old" },
  ]))));
  renderDetail();
  expect(await screen.findByRole("button", { name: "Download trace for test_ok" })).toHaveTextContent("Trace");
  expect(screen.queryByRole("button", { name: /Download trace for test_no/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Download trace for test_old/ })).toBeNull();
  expect(screen.getByText(/open it with npx playwright show-trace/i)).toBeInTheDocument();
});
