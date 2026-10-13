import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CaseEditorPage from "./CaseEditorPage";

const P = "/api/v1/projects/42";
const KEY = "Suite.Search.by city";
const FEATURE = [
  "Feature: Search", "  Background:", "    Given I am logged in", "", "  Scenario Outline: by city",
  "    When I search <city>", "    Then I see results", "      | name |", "      | x    |", "    Examples:",
  "      | city   |", "      | Lisbon |", "", "  Scenario: docs", "    Given a note:", '      """',
  "      Then not a step", '      """', "    Then it is saved",
].join("\n");
const GHERKIN = "Background:\n  Given I am logged in\nScenario Outline: by city\n  When I search <city>\n  Then I see results";

const kase = (extra: object = {}) => ({
  number: 7, key: "TC-7", title: "by city", description: null, steps: [], labels: [], priority: "medium", status: "draft",
  automated_test_key: KEY, automated_name: "by city", created_by: 1, created_at: "2026-10-06T10:00:00Z", updated_by: null,
  updated_at: null, suites: [], source_path: "f.feature", gherkin: GHERKIN, feature_name: "Search", ...extra,
});
const DETAIL = {
  feature_name: "Search", path: "f.feature", folder: "", content: FEATURE, imported_at: "2026-10-08T09:00:00Z",
  cases: [{ number: 7, key: "TC-7", scenario_name: "by city", line: 5, title: "by city", status: "draft", priority: "medium",
    labels: [], automated_test_key: KEY, automated_name: null, steps: [] }],
};
const result = (extra: object = {}) => ({
  status: "failed", run_id: 9, branch: "main", environment: null, started_at: new Date().toISOString(), message: "boom", ...extra,
});

let latestCalls = 0;
function setup(c: object, latest: object | null, detail: object = DETAIL) {
  latestCalls = 0;
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/cases/7`, () => HttpResponse.json(c)),
    http.get(`${P}/features/detail`, () => HttpResponse.json(detail)),
    http.get(`${P}/analytics/tests/:key/history`, () => HttpResponse.json({ executions: [] })),
    http.post(`${P}/analytics/latest-results`, () => {
      latestCalls++;
      return HttpResponse.json({ results: latest ? { [KEY.toLowerCase()]: latest } : {} });
    }),
  );
}

function renderCase() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/cases/7"]}>
        <Routes><Route path="/projects/:projectId/cases/:caseNumber" element={<CaseEditorPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("the failed step is red with its error, located through the feature file", async () => {
  setup(kase(), result({ failed_step: { text: "When I search Lisbon", line: 6 } }));
  renderCase();
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  const failed = document.querySelector(".gk-failed") as HTMLElement;
  expect(failed).toHaveTextContent("When I search <city>");
  act(() => failed.focus());
  expect(await screen.findByRole("tooltip")).toHaveTextContent("boom");
  expect(screen.getByText(/failed/i, { selector: ".badge *, .badge" })).toBeInTheDocument();
});

test("without the feature file's content it matches the case's own Gherkin by text", async () => {
  setup(kase(), result({ failed_step: { text: "Then I see results" } }), { ...DETAIL, content: null, cases: [] });
  renderCase();
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  expect(document.querySelector(".gk-failed")).toHaveTextContent("Then I see results");
});

test("a passed latest result marks nothing and shows Passed", async () => {
  setup(kase(), result({ status: "passed" }));
  renderCase();
  expect(await screen.findByText(/passed/i, { selector: ".badge *, .badge" })).toBeInTheDocument();
  await screen.findByRole("heading", { name: "Gherkin" });
  expect(document.querySelector(".gk-failed")).toBeNull();
});

test("no automated test key: no pill, no request", async () => {
  setup(kase({ automated_test_key: null, automated_name: null }), null);
  renderCase();
  await screen.findByRole("heading", { name: "Gherkin" });
  expect(screen.queryByText(/No runs yet/)).toBeNull();
  expect(latestCalls).toBe(0);
});

test("inside a Rule, the feature Background still counts: the red line is the failing step", async () => {
  const feature = ["Feature: F", "  Background:", "    Given outer", "  Rule: r", "    Scenario: s", "      When x", "      Then y"].join("\n");
  setup(
    kase({ gherkin: "Given outer\nWhen x\nThen y" }),
    result({ failed_step: { text: "Then y", line: 7 } }),
    { ...DETAIL, content: feature, cases: [{ ...DETAIL.cases[0], line: 5 }] },
  );
  renderCase();
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  expect(document.querySelector(".gk-failed")).toHaveTextContent("Then y");
  expect(document.querySelectorAll(".gk-failed")).toHaveLength(1);
});

test("a failed latest-results request still shows the Gherkin, with no pill", async () => {
  setup(kase(), null);
  server.use(http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  renderCase();
  await screen.findByRole("heading", { name: "Gherkin" });
  await waitFor(() => expect(document.querySelector(".gk-failed")).toBeNull());
  expect(screen.queryByText(/No runs yet/)).toBeNull();
  expect(document.querySelector(".badge")).toBeNull();
});

test("a hand-written case linked to a test shows the last-result pill, with no failed line", async () => {
  setup(kase({ source_path: null, gherkin: null, steps: [{ action: "Open", expected: "It opens" }] }), result({ failed_step: { text: "When I search Lisbon" } }));
  renderCase();
  expect(await screen.findByText(/failed/i, { selector: ".badge *, .badge" })).toBeInTheDocument();
  expect(document.querySelector(".gk-failed")).toBeNull();
});

test("the red line waits for the feature file instead of jumping from a provisional match", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const twice = ["Background:", "  Given I am logged in", "Scenario Outline: by city", "  Then ok", "  Then ok"].join("\n");
  setup(kase({ gherkin: twice }), result({ failed_step: { text: "Then ok", line: 9 } }), DETAIL);
  server.use(http.get(`${P}/features/detail`, async () => { await gate; return HttpResponse.json({ ...DETAIL, content: ["Feature: F", "Scenario: s", "  Given x", "  Then ok", "  Then ok", "", "", "", "  Then ok"].join("\n"), cases: [{ ...DETAIL.cases[0], line: 2 }] }); }));
  renderCase();
  await screen.findByText(/failed/i, { selector: ".badge *, .badge" });
  await new Promise((r) => setTimeout(r, 50));
  expect(document.querySelector(".gk-failed")).toBeNull();
  release();
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
});
