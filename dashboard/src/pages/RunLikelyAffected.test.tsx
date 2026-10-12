import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import type { SuggestedTest } from "../api/impact";
import CasesPage from "./CasesPage";

const P = "/api/v1/projects/42";
const TARGET = { available: true, configured: true, provider: "github", repo: "acme/obt", workflow: "qeos-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: null, updated_at: "2026-10-07T10:00:00Z", last_change: null };
const key = (name: string) => name.padEnd(64, "0");
const suggested = (name: string, kind: SuggestedTest["kind"]): SuggestedTest => ({
  test_key: key(name), suite: "s", class_name: "C", name, kind, evidence: null });
/** An imported case (runnable from QEOS) unless `manual`. */
const kase = (number: number, title: string, testKey: string, manual = false) => ({
  number, key: `TC-${number}`, title, description: null, steps: [], labels: [], priority: "medium", status: "ready",
  automated_test_key: testKey, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z", updated_by: null,
  updated_at: null, suites: [], source_path: manual ? null : "tests/features/a.feature", gherkin: manual ? null : "Scenario: x",
  feature_name: manual ? null : "A",
});
const RUN = {
  id: 70, project_id: 42, ci_provider: "github_actions", ci_run_url: null, commit_sha: "abcdef1234567890", branch: "main",
  environment: null, agent_version: null, commit_author: null, commit_message: null, pr_number: null, base_branch: null,
  started_at: "2026-10-12T09:00:00Z", finished_at: "2026-10-12T09:04:00Z", duration_ms: 240000, total: 3, passed: 3,
  failed: 0, skipped: 0, errored: 0, change_base_ref: "origin/main", changed_files: 2, additions: 4, deletions: 1,
  changes_truncated: false, created_at: "2026-10-12T09:05:00Z",
};

function asRole(role: string) {
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })));
}

beforeEach(() => {
  asRole("member");
  server.use(
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
    http.get(`${P}/ci-target`, () => HttpResponse.json(TARGET)),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 0, items: [] })),
  );
});

function mockImpact({ runs = [RUN], tests, cases, impact, paths = ["src/pay/api.py", "src/cart/x.py"] }: {
  runs?: object[]; paths?: string[]; tests: SuggestedTest[]; cases: object[]; impact?: () => Response;
}) {
  const bodies = { impact: [] as unknown[], search: [] as unknown[], estimate: [] as { test_keys: string[] }[] };
  server.use(
    http.get(`${P}/runs`, ({ request }) =>
      HttpResponse.json(new URL(request.url).searchParams.get("branch") === "main" ? runs : [])),
    http.get(`${P}/runs/70/impact`, () => HttpResponse.json({ run_id: 70, state: "ok",
      changed_paths: paths, replayed: false, scored_at: null, suggestion: null, outcome: null })),
    http.post(`${P}/analytics/impact`, async ({ request }) => {
      bodies.impact.push(await request.json());
      return impact ? impact() : HttpResponse.json({ state: "ok", model_version: "stats-v1", history_runs: 30, needed_runs: 20,
        statistical_total: 1, tests });
    }),
    http.post(`${P}/cases/search`, async ({ request }) => {
      const body = (await request.json()) as { test_keys: string[]; limit: number; offset: number };
      // The Cases tiles ask with other keys; only the panel's question gets the linked cases
      if (!tests.some((t) => body.test_keys.includes(t.test_key))) return HttpResponse.json({ total: 0, items: [] });
      bodies.search.push(body);
      return HttpResponse.json({ total: cases.length, items: cases.slice(body.offset, body.offset + body.limit) });
    }),
    http.post(`${P}/analytics/duration-estimate`, async ({ request }) => {
      bodies.estimate.push((await request.json()) as { test_keys: string[] });
      return HttpResponse.json({ estimate_ms: 360000, upper_ms: 420000, tests_with_history: 2, tests_without_history: 0,
        environment_used: 0, model: { overhead_ms: 0, factor: 1, runs: 5, fitted: true } });
    }),
  );
  return bodies;
}

function renderCases() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/cases?group=scenario"]}>
        <Routes><Route path="/projects/:projectId/cases" element={<CasesPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
}

async function findTests() {
  await userEvent.click(await screen.findByRole("button", { name: "Run likely affected" }));
  const panel = screen.getByRole("region", { name: "Run likely affected" });
  await waitFor(() => expect(within(panel).getByLabelText("Branch")).toHaveValue("main"));
  await userEvent.click(within(panel).getByRole("button", { name: "Find tests" }));
  return panel;
}

test("selects the linked cases, lists the unlinked tests, and the duration estimate follows the selection", async () => {
  const bodies = mockImpact({
    tests: [suggested("pays", "statistical"), suggested("cart", "failing_on_branch"), suggested("orphan", "no_history")],
    cases: [kase(2, "Cart totals", key("cart")), kase(1, "Pay by card", key("pays"))],
  });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("Selected 2 linked cases for 3 likely affected tests")).toBeInTheDocument();
  expect(bodies.impact).toEqual([{ changed_paths: ["src/pay/api.py", "src/cart/x.py"], branch: "main" }]);
  expect(bodies.search[0]).toMatchObject({ test_keys: [key("pays"), key("cart"), key("orphan")], keys_mode: "include",
    limit: 200, offset: 0 });
  expect(within(panel).getByRole("heading", { name: "Not runnable from QEOS (no linked case)" })).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "orphan" })).toHaveAttribute("href", `/projects/42/tests/${key("orphan")}`);
  expect(within(panel).getByRole("link", { name: "run #70" })).toHaveAttribute("href", "/projects/42/runs/70");
  // The ordinary selection: the bar's Run, and its estimate asked for exactly the selected cases' tests
  const bar = await screen.findByRole("region", { name: "Selected cases" });
  expect(within(bar).getByRole("button", { name: "Run selected (2)" })).toBeInTheDocument();
  await waitFor(() => expect(bodies.estimate.length).toBeGreaterThan(0));
  expect([...bodies.estimate.at(-1)!.test_keys].sort()).toEqual([key("cart"), key("pays")].sort());
  // Still a selection the person edits
  await userEvent.click(within(bar).getByRole("button", { name: "Clear selection" }));
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("a branch with no run carrying change data says so and selects nothing", async () => {
  mockImpact({ runs: [{ ...RUN, changed_files: null, change_base_ref: null }], tests: [], cases: [] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("No run on main has change data yet")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("suggestions with no linked case select nothing and are all listed", async () => {
  mockImpact({ tests: [suggested("orphan", "statistical")], cases: [] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("1 likely affected test, none linked to a case")).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "orphan" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("a failure shows with Retry, and Escape closes the panel back to its button", async () => {
  let calls = 0;
  mockImpact({ tests: [suggested("pays", "statistical")], cases: [kase(1, "Pay by card", key("pays"))],
    impact: () => (++calls === 1
      ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
      : HttpResponse.json({ state: "ok", model_version: "stats-v1", history_runs: 30, needed_runs: 20, statistical_total: 1,
        tests: [suggested("pays", "statistical")] })) });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(within(panel).getByRole("button", { name: "Retry" }));
  expect(await within(panel).findByText("Selected 1 linked case for 1 likely affected test")).toBeInTheDocument();
  // Retry is gone once the request succeeds: press Escape from inside the panel
  await userEvent.click(within(panel).getByLabelText("Branch"));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("region", { name: "Run likely affected" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run likely affected" })).toHaveFocus();
});

test("not enough history with nothing to suggest says so and selects nothing", async () => {
  mockImpact({ tests: [], cases: [], impact: () => HttpResponse.json({ state: "not_enough_history", model_version: "stats-v1",
    history_runs: 5, needed_runs: 20, statistical_total: 0, tests: [] }) });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("Not enough history on main yet to suggest tests: 5 of 20 runs with changed files"))
    .toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("nothing to suggest says so and selects nothing", async () => {
  mockImpact({ tests: [], cases: [] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("No tests are likely affected by the latest change on main")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

// Play's rule on this page: a role that cannot run gets no selection boxes, so no Run; Run likely affected follows it.
// Waits for the role to load first, so a button shown regardless of the role fails here.
test.each(["viewer", "billing_manager"])("a %s, who cannot Play, does not get the button", async (role) => {
  asRole(role);
  server.use(http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1, "Pay by card", key("pays"))] })));
  const qc = renderCases();
  await waitFor(() => expect(qc.getQueryData(["project", 42])).toMatchObject({ my_role: role }));
  expect(await screen.findByRole("link", { name: "Pay by card" })).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Run likely affected" })).not.toBeInTheDocument();
});

test("a member gets the button once the role loads", async () => {
  server.use(http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1, "Pay by card", key("pays"))] })));
  renderCases();
  expect(await screen.findByRole("button", { name: "Run likely affected" })).toHaveAttribute("aria-expanded", "false");
});

test("a test linked only to a manual case is listed as not runnable, never selected", async () => {
  mockImpact({ tests: [suggested("pays", "statistical")], cases: [kase(1, "Pay by card", key("pays"), true)] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("1 likely affected test, none linked to an imported case")).toBeInTheDocument();
  expect(within(panel).getByRole("heading", { name: "Not runnable from QEOS (linked only to a manual case)" })).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "pays" })).toHaveAttribute("href", `/projects/42/tests/${key("pays")}`);
  expect(within(panel).queryByRole("heading", { name: "Not runnable from QEOS (no linked case)" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("only imported cases are selected: a test with both kinds selects its imported case", async () => {
  const bodies = mockImpact({
    tests: [suggested("pays", "statistical"), suggested("cart", "failing_on_branch")],
    cases: [kase(1, "Pay by card", key("pays"), true), kase(2, "Cart totals", key("cart")), kase(3, "Cart by hand", key("cart"), true)],
  });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("Selected 1 linked case for 2 likely affected tests")).toBeInTheDocument();
  const notRunnable = within(panel).getByRole("list", { name: "Not runnable from QEOS (linked only to a manual case)" });
  expect(within(notRunnable).getAllByRole("link").map((a) => a.textContent)).toEqual(["pays"]);
  const bar = await screen.findByRole("region", { name: "Selected cases" });
  expect(within(bar).getByRole("button", { name: "Run selected (1)" })).toBeInTheDocument();
  await waitFor(() => expect(bodies.estimate.length).toBeGreaterThan(0));
  expect(bodies.estimate.at(-1)!.test_keys).toEqual([key("cart")]);
});

test("more than 200 linked cases: every page is read and the first 200 are selected", async () => {
  const many = Array.from({ length: 250 }, (_, i) => kase(i + 1, `Case ${i + 1}`, key("pays")));
  const bodies = mockImpact({ tests: [suggested("pays", "statistical")], cases: many });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText(
    "Selected 200 linked cases (the first 200: at most 200 cases per run) for 1 likely affected test")).toBeInTheDocument();
  expect((bodies.search as { offset: number }[]).map((b) => b.offset)).toEqual([0, 200]);
  const bar = await screen.findByRole("region", { name: "Selected cases" });
  expect(within(bar).getByRole("button", { name: "Run selected (200)" })).toBeInTheDocument();
});

test("the header button toggles the panel it controls, keeping focus on itself", async () => {
  mockImpact({ tests: [], cases: [] });
  renderCases();
  const button = await screen.findByRole("button", { name: "Run likely affected" });
  await userEvent.click(button);
  const panel = screen.getByRole("region", { name: "Run likely affected" });
  expect(button).toHaveAttribute("aria-expanded", "true");
  expect(button).toHaveAttribute("aria-controls", panel.id);
  expect(panel.id).not.toBe("");
  await userEvent.click(button);
  expect(screen.queryByRole("region", { name: "Run likely affected" })).not.toBeInTheDocument();
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(button).toHaveFocus();
});

test("a run that counts changed files but has none readable says so", async () => {
  mockImpact({ tests: [], cases: [], paths: [] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("Run #70 has no readable change data")).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "run #70" })).toHaveAttribute("href", "/projects/42/runs/70");
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});
