import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

test("a skipped result marks the step it stopped at in yellow, with the reason", async () => {
  setup(kase(), result({ status: "skipped", message: "Undefined step", failed_step: { text: "When I search Lisbon", line: 6 } }));
  renderCase();
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  const line = document.querySelector(".gk-failed") as HTMLElement;
  expect(line).toHaveClass("gk-skipped");
  expect(line).toHaveTextContent("When I search <city>");
  expect(line).toHaveTextContent(/skipped/i);
  act(() => line.focus());
  expect(await screen.findByRole("tooltip")).toHaveTextContent("Undefined step");
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

test("the log values show under the pill, each copyable, linked by its template", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  setup(kase(), result({ status: "passed", values: [
    { name: "route_key", values: ["wasToBos"], link_template: null },
    { name: "trip_id", values: ["3960562"], link_template: "https://backoffice.example.com/trips/{value}" },
  ] }));
  renderCase();
  const line = await screen.findByRole("group", { name: "Log values" });
  expect(line).toHaveTextContent(/route_key:\s*wasToBos/);
  // The template link beside the value; "Runs with trip_id 3960562" is the runs link
  expect(within(line).getByRole("link", { name: "Open trip_id 3960562 (opens in a new tab)" }))
    .toHaveAttribute("href", "https://backoffice.example.com/trips/3960562");
  await userEvent.click(within(line).getByRole("button", { name: "Copy route_key wasToBos" }));
  expect(writeText).toHaveBeenCalledWith("wasToBos");
  expect(await within(line).findByText("Copied")).toBeInTheDocument();
});

test("no log values, no line", async () => {
  setup(kase(), result({ status: "passed", values: [] }));
  renderCase();
  await screen.findByText(/passed/i, { selector: ".badge *, .badge" });
  expect(screen.queryByRole("group", { name: "Log values" })).toBeNull();
});

test("the case page links each value to its runs and shows no Log button (the run page has the log)", async () => {
  setup(kase(), result({ status: "passed", result_id: 77, values: [
    { name: "trip_id", values: ["3960562"], link_template: null },
  ] }));
  renderCase();
  const line = await screen.findByRole("group", { name: "Log values" });
  expect(within(line).getByRole("link", { name: "Runs with trip_id 3960562" }))
    .toHaveAttribute("href", "/projects/42/runs?value=3960562&pattern=trip_id");
  expect(within(line).getByRole("button", { name: "Copy trip_id 3960562" })).toHaveTextContent("3960562");
  expect(screen.queryByRole("button", { name: /^Log of/ })).toBeNull();
});

const shot = (step_text: string, step_line: number | null, count = 1, hook: "before" | "after" | null = null) =>
  ({ step_text, step_line, hook, count });

test("a step with screenshots has a camera button with the count, and no Screenshots link when all are placed", async () => {
  // The step's own image and the end-of-scenario image placed on it: one button for both
  setup(kase(), result({ result_id: 77, failed_step: { text: "When I search Lisbon", line: 6 },
    screenshot_steps: [shot("When I search Lisbon", 6), shot("When I search Lisbon", 6, 1, "after")] }));
  renderCase();
  const button = await screen.findByRole("button", { name: "Screenshots for this step (2)" });
  expect(button).toHaveTextContent("2");
  // On the failed line, beside its mark
  expect(button.closest(".gk-failed")).toHaveTextContent("When I search <city>");
  expect(screen.queryByRole("button", { name: /^Screenshots \(/ })).toBeNull();
});

test("one screenshot shows the camera without a visible count", async () => {
  setup(kase(), result({ status: "passed", result_id: 77, screenshot_steps: [shot("Then I see results", 7)] }));
  renderCase();
  const button = await screen.findByRole("button", { name: "Screenshots for this step (1)" });
  expect(button).not.toHaveTextContent("1");
});

test("a Background step's screenshots sit on the Background line of the case", async () => {
  setup(kase(), result({ status: "passed", result_id: 77, screenshot_steps: [shot("Given I am logged in", 3)] }));
  renderCase();
  const button = await screen.findByRole("button", { name: "Screenshots for this step (1)" });
  expect(button.closest(".gherkin > span")).toHaveTextContent("Given I am logged in");
});

test("a step edited since the run puts its screenshots under a Screenshots link that opens the viewer", async () => {
  setup(kase(), result({ status: "passed", result_id: 77, screenshot_steps: [shot("When I filter by price", 6, 2)] }));
  server.use(http.get(`${P}/runs/9/results/77/screenshots`, () => HttpResponse.json({ screenshots: [] })));
  renderCase();
  const link = await screen.findByRole("button", { name: "Screenshots (2)" });
  expect(screen.queryByRole("button", { name: /^Screenshots for this step/ })).toBeNull();
  await userEvent.click(link);
  expect(await screen.findByRole("dialog", { name: /Screenshots — by city/ })).toBeInTheDocument();
});

test("a manual case that carries Gherkin shows no step lines, so its screenshots all go under the Screenshots link", async () => {
  setup(kase({ source_path: null }), result({ status: "passed", result_id: 77, screenshot_steps: [shot("Then I see results", 7, 2)] }));
  renderCase();
  expect(await screen.findByRole("button", { name: "Screenshots (2)" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Screenshots for this step/ })).toBeNull();
});

test("no screenshot steps, no camera and no link", async () => {
  setup(kase(), result({ status: "passed", result_id: 77 }));
  renderCase();
  await screen.findByText(/passed/i, { selector: ".badge *, .badge" });
  expect(screen.queryByRole("button", { name: /^Screenshots/ })).toBeNull();
});

test("a viewer, who cannot edit the case, can still open its screenshots", async () => {
  setup(kase(), result({ status: "passed", result_id: 77, screenshot_steps: [shot("Then I see results", 7, 2)] }));
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "viewer" })));
  renderCase();
  await screen.findByText(/only owners, admins and members can change test cases/i);
  expect(await screen.findByRole("button", { name: "Screenshots for this step (2)" })).toBeEnabled();
});

test("a result with traces shows a Trace button beside the pill and the show-trace note; none without", async () => {
  setup(kase(), result({ result_id: 77, trace_count: 1 }));
  renderCase();
  expect(await screen.findByRole("button", { name: "Download trace for TC-7" })).toHaveTextContent("Trace");
  expect(screen.getByText(/open it with npx playwright show-trace/i)).toBeInTheDocument();
});

test("no Trace button when the result has no traces or the server does not say", async () => {
  setup(kase(), result({ result_id: 77 }));
  renderCase();
  await screen.findByText(/failed/i);
  expect(screen.queryByRole("button", { name: /Download trace/ })).toBeNull();
  expect(screen.queryByText(/playwright show-trace/i)).toBeNull();
});
