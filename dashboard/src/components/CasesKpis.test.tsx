import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CasesPage from "../pages/CasesPage";

const P = "/api/v1/projects/42";

function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="where">{pathname + search}</p>;
}

const week = (pass_rate: number | null, runs = 4) => ({
  date: "2026-09-28", runs, total: 100, passed: 90, failed: 10, errored: 0, skipped: 0, pass_rate,
  avg_run_duration_ms: null, max_run_duration_ms: null,
});
const flakyRow = (key: string, muted: boolean) => ({
  test_key: key, muted, suite: "s", class_name: "c", name: key, reason: "flips", commits: [], flips: 3, flip_rate: 0.5,
  runs: 6, last_status: "passed", last_seen: "2026-10-01T00:00:00Z",
});

let failingSearch: Record<string, unknown> | null;
let searches = 0;
let failedKeyAsks = 0;
const kase = (n: number) => ({
  number: n, key: `TC-${n}`, title: `Case ${n}`, description: null, steps: [], labels: [], priority: "medium", status: "ready",
  automated_test_key: "f".repeat(64), automated_name: null, created_by: 1, created_at: "2026-01-01T00:00:00Z", updated_by: null,
  updated_at: null, source_path: null, gherkin: null, feature_name: null, suites: [],
});

function apis({ thisWeek = 0.924 as number | null, lastWeek = 0.893 as number | null, failing = 17 } = {}) {
  failingSearch = null;
  searches = 0;
  failedKeyAsks = 0;
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, ({ request }) =>
      HttpResponse.json({ total: new URL(request.url).searchParams.get("origin") === "imported" ? 991 : 1083, items: [] })),
    http.get(`${P}/analytics/trends`, () =>
      HttpResponse.json({ tz: "UTC", bucket: "week", days: [week(lastWeek), week(thisWeek)] })),
    http.get(`${P}/analytics/latest-keys`, ({ request }) => {
      if (new URL(request.url).searchParams.get("status") === "failed") failedKeyAsks += 1;
      return HttpResponse.json({ keys: failing > 0 ? ["f".repeat(64)] : [] });
    }),
    http.post(`${P}/cases/search`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      searches += 1;
      failingSearch = body;
      return HttpResponse.json({ total: failing, items: failing > 0 ? [kase(1)] : [] });
    }),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ tests: {} })),
    http.get(`${P}/analytics/flaky`, () =>
      HttpResponse.json([flakyRow("a", false), flakyRow("b", false), flakyRow("c", false), flakyRow("d", true), flakyRow("e", true)])),
  );
}

function renderCases(url = "/projects/42/cases?group=scenario") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/projects/:projectId/cases" element={<><CasesPage /><Where /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const tiles = () => screen.getByRole("list", { name: "Case summary" });

test("four tiles: totals, pass rate trend, failing and flaky counts, each with a full label", async () => {
  apis();
  renderCases();
  const cases = await within(tiles()).findByRole("group", { name: "Cases 1,083, 991 imported" });
  expect(cases).toHaveClass("kpi-neutral");
  expect(cases).toHaveTextContent("1,083");
  expect(cases).toHaveTextContent("991 imported");

  const rate = await within(tiles()).findByRole("group", { name: "Pass rate 92.4%, up 3.1 points versus last week" });
  expect(rate).toHaveClass("kpi-good");
  expect(rate).toHaveTextContent("92.4%");
  expect(rate).toHaveTextContent("up 3.1 pts");

  const failing = await within(tiles()).findByRole("link", { name: "Failing 17 linked cases whose latest result failed" });
  expect(failing).toHaveClass("kpi-bad");
  expect(failing).toHaveAttribute("href", "/projects/42/cases?group=scenario&result=failed");
  expect(failingSearch).toMatchObject({ test_keys: ["f".repeat(64)], keys_mode: "include" });

  const flaky = await within(tiles()).findByRole("link", { name: "Flaky 3 tests in the last 14 days, 2 quarantined" });
  expect(flaky).toHaveAttribute("href", "/projects/42/flaky");
  expect(flaky).toHaveTextContent("2 quarantined");
});

test("the Failing count is the Failing filter's total, from the same requests", async () => {
  apis();
  renderCases("/projects/42/cases?group=scenario&result=failed");
  expect(await within(tiles()).findByRole("link", { name: /^Failing 17 / })).toBeInTheDocument();
  expect(await screen.findByText("1–1 of 17")).toBeInTheDocument();
  // The list and the tile share their keys: one ask for failed keys, one search
  expect(failedKeyAsks).toBe(1);
  expect(searches).toBe(1);
});

test("each tile names its tone with an icon beside the title, never colour alone", async () => {
  apis();
  renderCases();
  const failing = await within(tiles()).findByRole("link", { name: /^Failing 17/ });
  expect(failing.querySelector(".kpi-tone svg")).not.toBeNull();
  const rate = await within(tiles()).findByRole("group", { name: /^Pass rate 92.4%/ });
  expect(rate.querySelector(".kpi-tone svg")).not.toBeNull();
});

test("the tiles sit under the page header, above the quick filters", async () => {
  apis();
  renderCases();
  const heading = screen.getByRole("heading", { level: 1, name: "Test cases" });
  const chips = await screen.findByRole("group", { name: "Quick filters" });
  expect(heading.compareDocumentPosition(tiles()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(tiles().compareDocumentPosition(chips) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("a falling pass rate reads down, with a red edge", async () => {
  apis({ thisWeek: 0.9, lastWeek: 0.92 });
  renderCases();
  const rate = await within(tiles()).findByRole("group", { name: "Pass rate 90.0%, down 2.0 points versus last week" });
  expect(rate).toHaveClass("kpi-bad");
  expect(rate).toHaveTextContent("down 2.0 pts");
});

test("an unchanged pass rate reads flat, with a green edge", async () => {
  apis({ thisWeek: 0.9, lastWeek: 0.9 });
  renderCases();
  const rate = await within(tiles()).findByRole("group", { name: "Pass rate 90.0%, flat versus last week" });
  expect(rate).toHaveClass("kpi-good");
  expect(rate).toHaveTextContent("flat");
});

test("with no runs the week before there is no trend and the edge stays neutral", async () => {
  apis({ lastWeek: null });
  renderCases();
  const rate = await within(tiles()).findByRole("group", { name: "Pass rate 92.4%, no runs the week before" });
  expect(rate).toHaveClass("kpi-neutral");
});

test("no failing cases keeps the Failing edge neutral", async () => {
  apis({ failing: 0 });
  renderCases();
  const failing = await within(tiles()).findByRole("link", { name: "Failing 0 linked cases whose latest result failed" });
  expect(failing).toHaveClass("kpi-neutral");
});

test("the Failing tile applies the Failing quick chip", async () => {
  apis();
  renderCases("/projects/42/cases?group=scenario&status=ready");
  await userEvent.setup().click(await screen.findByRole("link", { name: /^Failing 17/ }));
  expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/cases?group=scenario&result=failed");
  expect(await screen.findByRole("button", { name: "Failing", pressed: true })).toBeInTheDocument();
});

test("an error shows a dash and Retry in that tile only", async () => {
  apis();
  let fail = true;
  server.use(http.get(`${P}/analytics/trends`, () =>
    fail ? HttpResponse.json({ detail: "down" }, { status: 503 }) : HttpResponse.json({ tz: "UTC", bucket: "week", days: [week(0.8), week(0.85)] })));
  renderCases();
  const rate = await within(tiles()).findByRole("group", { name: "Pass rate unavailable" });
  expect(rate).toHaveTextContent("—");
  expect(within(tiles()).getAllByRole("button", { name: /Retry/ })).toHaveLength(1);
  expect(await within(tiles()).findByRole("group", { name: /^Cases 1,083/ })).toBeInTheDocument();
  expect(await within(tiles()).findByRole("link", { name: /^Flaky 3/ })).toBeInTheDocument();
  fail = false;
  await userEvent.setup().click(within(rate).getByRole("button", { name: "Retry pass rate" }));
  expect(await within(tiles()).findByRole("group", { name: "Pass rate 85.0%, up 5.0 points versus last week" })).toBeInTheDocument();
});

test("a failing tile that cannot load is not a link, and retries on its own", async () => {
  apis();
  server.use(http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ detail: "down" }, { status: 503 })));
  renderCases();
  const failing = await within(tiles()).findByRole("group", { name: "Failing unavailable" });
  expect(within(failing).getByRole("button", { name: "Retry failing" })).toBeInTheDocument();
  expect(within(tiles()).queryByRole("link", { name: /^Failing/ })).not.toBeInTheDocument();
});

test("the imported count is dropped when it cannot be had", async () => {
  apis();
  server.use(http.get(`${P}/cases`, ({ request }) =>
    new URL(request.url).searchParams.get("origin") === "imported"
      ? HttpResponse.json({ detail: "x" }, { status: 500 })
      : HttpResponse.json({ total: 1083, items: [] })));
  renderCases();
  const cases = await within(tiles()).findByRole("group", { name: "Cases 1,083" });
  expect(cases).not.toHaveTextContent("imported");
});

test("each tile has its own loading skeleton", async () => {
  apis();
  renderCases();
  expect(within(tiles()).getAllByRole("status")).toHaveLength(4);
  await within(tiles()).findByRole("link", { name: /^Flaky 3/ });
});
