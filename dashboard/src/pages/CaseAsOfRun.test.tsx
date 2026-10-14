import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CaseEditorPage from "./CaseEditorPage";
import FeaturePage from "./FeaturePage";

// Opened from a Last runs bar: the case, or the feature, as of one run, with its failed steps marked
const P = "/api/v1/projects/42";
const KEY = "Suite.Search.by city";
const OTHER = "Suite.Search.docs";
const FEATURE = [
  "Feature: Search", "", "  Scenario: by city", "    When I search Lisbon", "    Then I see results", "",
  "  Scenario: docs", "    Then it is saved",
].join("\n");
const kase = (extra: object = {}) => ({
  number: 7, key: "TC-7", title: "by city", description: null, steps: [], labels: [], priority: "medium", status: "draft",
  automated_test_key: KEY, automated_name: "by city", created_by: 1, created_at: "2026-10-06T10:00:00Z", updated_by: null,
  updated_at: null, suites: [], source_path: "f.feature", gherkin: "Scenario: by city\n  When I search Lisbon\n  Then I see results",
  feature_name: "Search", ...extra,
});
const scenario = (number: number, name: string, line: number, key: string) => ({
  number, key: `TC-${number}`, scenario_name: name, line, title: name, status: "draft", priority: "medium",
  labels: [], automated_test_key: key, automated_name: null, steps: [],
});
const DETAIL = {
  feature_name: "Search", path: "f.feature", folder: "", content: FEATURE, imported_at: "2026-10-08T09:00:00Z",
  cases: [scenario(7, "by city", 3, KEY), scenario(8, "docs", 7, OTHER)],
};
const failedInRun = {
  status: "failed", run_id: 5, branch: "main", environment: null, started_at: "2026-10-06T10:02:00Z", message: "boom",
  failed_step: { text: "When I search Lisbon", line: 4 },
};

let bodies: { keys: string[]; run_id?: number }[] = [];
function setup({ c = kase(), results = {} as Record<string, object>, status = 200 } = {}) {
  bodies = [];
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/cases/7`, () => HttpResponse.json(c)),
    http.get(`${P}/features/detail`, () => HttpResponse.json(DETAIL)),
    http.get(`${P}/analytics/tests/:key/history`, () => HttpResponse.json({ executions: [] })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ tests: {} })),
    http.post(`${P}/analytics/latest-results`, async ({ request }) => {
      bodies.push(await request.json() as { keys: string[]; run_id?: number });
      return status === 200 ? HttpResponse.json({ results }) : HttpResponse.json({ detail: "Run not found" }, { status });
    }),
  );
}

function renderAt(url: string) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/cases/feature" element={<FeaturePage />} />
          <Route path="/projects/:projectId/cases/:caseNumber" element={<CaseEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a case opened as of a run asks for that run, says so and marks that run's failed step", async () => {
  setup({ results: { [KEY.toLowerCase()]: failedInRun } });
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  expect(document.querySelector(".gk-failed")).toHaveTextContent("When I search Lisbon");
  expect(bodies[0]).toEqual({ keys: [KEY], run_id: 5 });
  expect(document.querySelector(".run-context")).toHaveTextContent(/Showing run #5, .+: Failed\./);
  expect(screen.getByRole("link", { name: "run #5" })).toHaveAttribute("href", "/projects/42/runs/5");
  expect(screen.getByRole("link", { name: "Show latest" })).toHaveAttribute("href", "/projects/42/cases/7");
});

test("a case that was not in the run says so, with no marked step", async () => {
  setup();
  renderAt("/projects/42/cases/7?run=5");
  expect(await screen.findByText(/This case was not in run #5\./)).toBeInTheDocument();
  expect(document.querySelector(".gk-failed")).toBeNull();
  // The run note says it; no "No runs yet" pill contradicts it
  expect(screen.queryByText("No runs yet")).toBeNull();
});

test("a run of another project says it is not in this project", async () => {
  setup({ status: 404 });
  renderAt("/projects/42/cases/7?run=5");
  expect(await screen.findByText(/Run #5 is not in this project\./)).toBeInTheDocument();
});

test("without a valid run the case shows its latest result and asks without run_id", async () => {
  setup({ results: { [KEY.toLowerCase()]: failedInRun } });
  renderAt("/projects/42/cases/7?run=abc");
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0]).toEqual({ keys: [KEY] });
  expect(document.querySelector(".run-context")).toBeNull();
});

test("a feature opened as of a run marks each failed scenario and names those not in the run", async () => {
  setup({ results: { [KEY.toLowerCase()]: failedInRun } });
  renderAt("/projects/42/cases/feature?path=f.feature&run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  expect(document.querySelector(".gk-failed")).toHaveTextContent("When I search Lisbon");
  expect(bodies[0]).toEqual({ keys: [KEY, OTHER], run_id: 5 });
  expect(screen.getByText("Not in run #5")).toBeInTheDocument();
  expect(screen.getByText("1 failed · 1 not in run")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Show latest" })).toHaveAttribute("href", "/projects/42/cases/feature?path=f.feature");
});

const STEP_KEY = "a1b2c3d4e5f60718";
let stepRequests: string[] = [];
function withSteps(answer: object) {
  stepRequests = [];
  server.use(http.get(`${P}/runs/:runId/failed-steps`, ({ params }) => {
    stepRequests.push(String(params.runId));
    return HttpResponse.json(answer);
  }));
}
const spreadStep = (cases: number, runs: number) => ({ steps: [{
  key: STEP_KEY, by: "definition", pattern: "When I search {…}", cases, errors: [],
  since: { run_id: runs === 1 ? 5 : 430, started_at: "2026-10-01T10:00:00Z", runs, capped: false } }] });
const keyed = { ...failedInRun, failed_step: { ...failedInRun.failed_step, key: STEP_KEY } };

test("the tooltip says how many other test cases failed at the step, linking to its row on the run page", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed } });
  withSteps(spreadStep(12, 5));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  const tip = await screen.findByRole("tooltip");
  const link = await within(tip).findByRole("link", { name: "Also failed in 11 other test cases in this run · failing since run #430" });
  expect(link).toHaveAttribute("href", `/projects/42/runs/5#step-${STEP_KEY}`);
  expect(stepRequests).toEqual(["5"]);
});

test("only this test case, new in this run", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed } });
  withSteps(spreadStep(1, 1));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  expect(await within(await screen.findByRole("tooltip")).findByRole("link", { name: "Only this test case · new in this run" })).toBeInTheDocument();
});

test("without a step key (an older server) the tooltip has no spread line and asks nothing", async () => {
  setup({ results: { [KEY.toLowerCase()]: failedInRun } });
  withSteps(spreadStep(12, 5));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  expect(await screen.findByRole("tooltip")).not.toHaveTextContent(/Also failed|Only this test case/);
  expect(stepRequests).toEqual([]);
});

test("a feature page asks once per run for all its cards", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed, [OTHER.toLowerCase()]: { ...keyed, failed_step: { text: "Then it is saved", line: 8, key: STEP_KEY } } } });
  withSteps(spreadStep(2, 5));
  renderAt("/projects/42/cases/feature?path=f.feature&run=5");
  await waitFor(() => expect(document.querySelectorAll(".gk-failed").length).toBe(2));
  await waitFor(() => expect(stepRequests).toEqual(["5"]));
});

test("a failed failed-steps request leaves the tooltip as it was", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed } });
  stepRequests = [];
  server.use(http.get(`${P}/runs/:runId/failed-steps`, () => HttpResponse.json({ detail: "x" }, { status: 500 })));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  const tip = await screen.findByRole("tooltip");
  expect(tip).toHaveTextContent("boom");
  expect(tip).not.toHaveTextContent(/Also failed|Only this test case/);
});
