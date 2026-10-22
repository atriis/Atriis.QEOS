import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import FeaturePage from "./FeaturePage";

const P = "/api/v1/projects/42";
const KEY = "d".repeat(64);
const KEY2 = "e".repeat(64);
const PATH = "features/auth/login.feature";
const URL_ = `/projects/42/cases/feature?path=${encodeURIComponent(PATH)}`;
const TARGET = { available: true, configured: true, provider: "github", repo: "acme/obt", workflow: "qeos-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: null, updated_at: "2026-10-07T10:00:00Z", last_change: null };

const CONTENT = [
  "@auth",
  "Feature: Login",
  "",
  "  Scenario: Good password",
  '    Given I type "secret"',
  "",
  "  Scenario: Bad password",
  "    Then I see an error",
].join("\n");

const detailCase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Title ${number}`, scenario_name: `Scenario ${number}`, status: "ready",
  priority: "high", automated_test_key: null, line: null, ...extra,
});
const DETAIL = {
  feature_name: "Login", path: PATH, folder: "features/auth", content: CONTENT, imported_at: "2026-10-08T09:00:00Z",
  cases: [
    detailCase(12, { scenario_name: "Good password", line: 4, automated_test_key: KEY }),
    detailCase(13, { scenario_name: "Bad password", line: 7, automated_test_key: KEY2 }),
  ],
};

const kase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Title ${number}`, description: null, steps: [], labels: [], priority: "medium",
  status: "ready", automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z",
  updated_by: null, updated_at: null, suites: [], source_path: PATH, gherkin: null, feature_name: "Login", ...extra,
});

const result = (status: string, extra: object = {}) => ({
  status, run_id: 9, branch: "main", environment: null, started_at: "2026-10-08T09:00:00Z", message: null, ...extra,
});

function asRole(role: string) {
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })));
}

beforeEach(() => {
  asRole("member");
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(TARGET)),
    http.get(`${P}/features/detail`, ({ request }) =>
      new URL(request.url).searchParams.get("path") === PATH
        ? HttpResponse.json(DETAIL)
        : HttpResponse.json({ detail: "Feature not found" }, { status: 404 })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {} })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({
      tests: { [KEY]: [{ run_id: 7, started_at: "2026-10-08T09:00:00Z", branch: "main", status: "failed" }] },
    })),
  );
});

function renderAt(url = URL_) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/projects/:projectId/cases/feature" element={<FeaturePage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("the header names the file; each scenario is a card linking its case, with its run strip", async () => {
  renderAt();
  expect(await screen.findByRole("heading", { level: 1, name: "Login" })).toBeInTheDocument();
  expect(screen.getByText(PATH)).toBeInTheDocument();
  const cards = await screen.findAllByRole("article");
  expect(cards).toHaveLength(2);
  expect(within(cards[0]).getByRole("link", { name: "TC-12" })).toHaveAttribute("href", "/projects/42/cases/12");
  expect(within(cards[1]).getByRole("link", { name: "TC-13" })).toHaveAttribute("href", "/projects/42/cases/13");
  // A bar opens the scenario's case as of its run
  expect(within(within(cards[0]).getByRole("group", { name: /Last 1 run/ })).getByRole("link")).toHaveAttribute("href", expect.stringMatching(/^\/projects\/42\/cases\/12\?run=\d+$/));
  // The scenario's own lines, numbered as in the file
  expect(cards[1].querySelectorAll(".gk-line")).toHaveLength(2);
  expect(cards[1].querySelector(".gk-line")).toHaveAttribute("data-line", "7");
  expect(screen.queryByText(/Re-import this file/)).not.toBeInTheDocument();
});

test("one card per scenario with its status, Background once", async () => {
  server.use(http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: { [KEY]: result("passed") } })));
  renderAt();
  const cards = await screen.findAllByRole("article");
  expect(cards).toHaveLength(2);
  expect(await within(cards[0]).findByText(/Passed/)).toBeInTheDocument();
  expect(within(cards[1]).getByText("No runs yet")).toBeInTheDocument();
  expect(screen.getByText("1 passed · 1 no runs")).toBeInTheDocument();
  // The preamble (tag, Feature line) is shown once, outside the cards
  expect(screen.getByLabelText("Feature")).toHaveTextContent("Feature: Login");
  for (const card of cards) expect(card).not.toHaveTextContent("Feature: Login");
});

test("the failed step is red on its card, with the error", async () => {
  server.use(http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
    [KEY2]: result("failed", { message: "expected an error banner", failed_step: { text: "Then I see an error", line: 8 } }),
  } })));
  renderAt();
  const cards = await screen.findAllByRole("article");
  await waitFor(() => expect(cards[1].querySelector(".gk-failed")).not.toBeNull());
  expect(cards[0].querySelector(".gk-failed")).toBeNull();
  const failed = cards[1].querySelector(".gk-failed") as HTMLElement;
  expect(failed).toHaveTextContent("Then I see an error");
  expect(failed).toHaveAttribute("data-line", "8");
  act(() => failed.focus());
  const tip = await screen.findByRole("tooltip");
  expect(tip).toHaveTextContent("expected an error banner");
  expect(within(tip).getByRole("link", { name: "Open run" })).toHaveAttribute("href", "/projects/42/runs/9");
  expect(screen.getByText("1 failed · 1 no runs")).toBeInTheDocument();
});

test("a skipped scenario's stopping step is yellow on its card, with the reason", async () => {
  server.use(http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
    [KEY2]: result("skipped", { message: "Undefined step", failed_step: { text: "Then I see an error", line: 8 } }),
  } })));
  renderAt();
  const cards = await screen.findAllByRole("article");
  await waitFor(() => expect(cards[1].querySelector(".gk-failed")).not.toBeNull());
  const line = cards[1].querySelector(".gk-failed") as HTMLElement;
  expect(line).toHaveClass("gk-skipped");
  expect(line).toHaveTextContent("Then I see an error");
  expect(line).toHaveTextContent(/skipped/i);
  act(() => line.focus());
  expect(await screen.findByRole("tooltip")).toHaveTextContent("Undefined step");
});

test("a Background step that skipped the scenario is named on the card", async () => {
  const content = ["Feature: Login", "", "  Background:", "    Given bg", "", "  Scenario: Good password", "    When a", "",
    "  Scenario: Bad password", "    Then b"].join("\n");
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content, cases: [
      detailCase(12, { scenario_name: "Good password", line: 6, automated_test_key: KEY }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("skipped", { message: "Pending step", failed_step: { text: "Given bg", line: 4 } }),
    } })),
  );
  renderAt();
  const note = await screen.findByText("Skipped in Background: Given bg");
  expect(note).toHaveClass("is-skipped");
  act(() => note.focus());
  expect(await screen.findByRole("tooltip")).toHaveTextContent("Pending step");
});

test("a Background failure is named on the card", async () => {
  const content = ["Feature: Login", "", "  Background:", "    Given bg", "", "  Scenario: Good password", "    When a", "",
    "  Scenario: Bad password", "    Then b"].join("\n");
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content, cases: [
      detailCase(12, { scenario_name: "Good password", line: 6, automated_test_key: KEY }),
      detailCase(13, { scenario_name: "Bad password", line: 9, automated_test_key: KEY2 }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("failed", { message: "bg broke", failed_step: { text: "Given bg", line: 4 } }),
    } })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  const note = await within(cards[0]).findByText("Failed in Background: Given bg");
  expect(within(cards[1]).queryByText(/Failed in Background/)).not.toBeInTheDocument();
  expect(document.querySelector(".gk-failed")).toBeNull();
  expect(screen.getByLabelText("Feature")).toHaveTextContent("Background:");
  act(() => note.focus());
  expect(await screen.findByRole("tooltip")).toHaveTextContent("bg broke");
});

test("the Background note has the full tip keyboard path: Tab to Open run, Escape returns to the note", async () => {
  const content = ["Feature: Login", "", "  Background:", "    Given bg", "", "  Scenario: Good password", "    When a"].join("\n");
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content, cases: [
      detailCase(12, { scenario_name: "Good password", line: 6, automated_test_key: KEY }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("failed", { message: "bg broke", failed_step: { text: "Given bg", line: 4 } }),
    } })),
  );
  renderAt();
  const note = (await screen.findByText("Failed in Background: Given bg")) as HTMLElement;
  act(() => note.focus());
  const tip = await screen.findByRole("tooltip");
  expect(note).toHaveAttribute("aria-describedby", tip.id);
  expect(tip.parentElement).toBe(document.body);
  await userEvent.tab();
  expect(document.activeElement).toBe(within(tip).getByRole("link", { name: "Open run" }));
  await userEvent.keyboard("{Escape}");
  expect(document.activeElement).toBe(note);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("a failed step in a Rule-level Background is named on the card too", async () => {
  const content = ["Feature: Login", "", "  Rule: r", "    Background:", "      Given rule bg", "", "    Scenario: Good password", "      When a"].join("\n");
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content, cases: [
      detailCase(12, { scenario_name: "Good password", line: 7, automated_test_key: KEY }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("failed", { message: "rule bg broke", failed_step: { text: "Given rule bg", line: 5 } }),
    } })),
  );
  renderAt();
  expect(await screen.findByText("Failed in Background: Given rule bg")).toBeInTheDocument();
  expect(document.querySelector(".gk-failed")).toBeNull();
});

test("duplicate automated keys are sent once", async () => {
  const bodies: { keys: string[] }[] = [];
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, cases: [
      detailCase(12, { line: 4, automated_test_key: KEY }),
      detailCase(13, { line: 7, automated_test_key: KEY }),
    ] })),
    http.post(`${P}/analytics/latest-results`, async ({ request }) => {
      bodies.push(await request.json() as { keys: string[] });
      return HttpResponse.json({ results: {} });
    }),
  );
  renderAt();
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].keys).toEqual([KEY]);
});

test("one latest-results request per 500 cases", async () => {
  const keys = Array.from({ length: 501 }, (_, i) => i.toString(16).padStart(64, "0"));
  const bodies: { keys: string[] }[] = [];
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, cases: keys.map((k, i) => detailCase(100 + i, { automated_test_key: k })) })),
    http.post(`${P}/analytics/latest-results`, async ({ request }) => {
      bodies.push(await request.json() as { keys: string[] });
      return HttpResponse.json({ results: {} });
    }),
  );
  renderAt();
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies.map((b) => b.keys.length).sort((x, y) => x - y)).toEqual([1, 500]);
});

test("a file stored before raw content: cards from each case's Gherkin, text matching", async () => {
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content: null, imported_at: null,
      cases: DETAIL.cases.map((c) => ({ ...c, line: null })) })),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 2, items: [
      kase(12, { gherkin: "@smoke\nScenario: Good password\n  Given I type \"secret\"" }),
      kase(13, { gherkin: "Scenario: Bad password\n  Then I see an error" }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      // The recorded line (99) means nothing here: the step is found by its text
      [KEY2]: result("failed", { message: "no banner", failed_step: { text: "Then I see an error", line: 99 } }),
    } })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  await waitFor(() => expect(cards[1].querySelector(".gk-failed")).not.toBeNull());
  expect(cards[1].querySelector(".gk-failed")).toHaveTextContent("Then I see an error");
  expect(cards[0].querySelector(".gk-failed")).toBeNull();
});

test("Run feature asks to run every scenario of the file", async () => {
  renderAt();
  await userEvent.click(await screen.findByRole("button", { name: "Run feature" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByRole("heading", { name: "Run 2 tests?" })).toBeInTheDocument();
  expect(within(dialog).getByText("TC-12 · Title 12")).toBeInTheDocument();
});

test("a viewer reads the file but has no Run feature", async () => {
  asRole("viewer");
  renderAt();
  await screen.findAllByRole("article");
  expect(screen.queryByRole("button", { name: "Run feature" })).not.toBeInTheDocument();
});

test("without the stored file the scenarios are rebuilt from the cases, with a note", async () => {
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content: null, imported_at: null,
      cases: DETAIL.cases.map((c) => ({ ...c, line: null })) })),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 3, items: [
      kase(12, { gherkin: "@smoke\nScenario: Good password\n  Given I type \"secret\"" }),
      kase(13, { gherkin: null }),
      kase(40, { source_path: "features/other.feature" }),
    ] })),
  );
  renderAt();
  expect(await screen.findByText("Re-import this file to see it exactly as written.")).toBeInTheDocument();
  const cards = await screen.findAllByRole("article");
  expect(cards).toHaveLength(2);
  expect(cards[0]).toHaveTextContent("Scenario: Good password");
  // A case with no stored Gherkin is shown by its title
  expect(cards[1]).toHaveTextContent("Scenario: Title 13");
  expect(document.body).not.toHaveTextContent("Title 40");
  expect(within(cards[0]).getByRole("link", { name: "TC-12" })).toBeInTheDocument();
});

test("an unknown or archived file says it is not found", async () => {
  renderAt("/projects/42/cases/feature?path=features%2Fgone.feature");
  expect(screen.getByRole("heading", { level: 1, name: "gone" })).toBeInTheDocument();
  expect(await screen.findByText(/Feature not found/)).toBeInTheDocument();
});

test("a rebuilt file with a Background in the case's Gherkin still reddens the failed scenario step", async () => {
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content: null, imported_at: null,
      cases: [detailCase(12, { scenario_name: "Good password", line: null, automated_test_key: KEY })] })),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [
      kase(12, { automated_test_key: KEY, gherkin: ["Background:", "  Given bg", "Scenario: Good password", "  When a", "  Then b"].join("\n") }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("failed", { failed_step: { text: "Then b" } }),
    } })),
  );
  renderAt();
  await screen.findAllByRole("article");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  expect(document.querySelector(".gk-failed")).toHaveTextContent("Then b");
  expect(screen.queryByText(/Failed in Background/)).not.toBeInTheDocument();
});

test("a scenario card shows its log values under its pill", async () => {
  server.use(http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
    [KEY]: result("passed", { values: [{ name: "trip_id", values: ["3960562", "3960563"], link_template: null }] }),
  } })));
  renderAt();
  const cards = await screen.findAllByRole("article");
  const line = await within(cards[0]).findByRole("group", { name: "Log values of TC-12" });
  expect(line).toHaveTextContent(/trip_id:\s*3960562.*3960563/); // each value is followed by its "runs" link
  expect(within(cards[1]).queryByRole("group", { name: /Log values/ })).toBeNull();
});

test("a scenario card links its values to their runs and shows no Log button (the run page has the log)", async () => {
  server.use(
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("passed", { result_id: 77, values: [{ name: "trip_id", values: ["3960562"], link_template: null }] }),
    } })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  const line = await within(cards[0]).findByRole("group", { name: "Log values of TC-12" });
  expect(within(line).getByRole("link", { name: "Runs with trip_id 3960562" })).toHaveAttribute("href", "/projects/42/runs?value=3960562&pattern=trip_id");
  expect(within(line).getByRole("button", { name: "Copy trip_id 3960562" })).toHaveTextContent("3960562");
  expect(within(cards[0]).queryByRole("button", { name: /^Log of/ })).toBeNull();
});

test("a scenario's step screenshots sit on its card; a Background step's go to its Screenshots link, never the shared Background", async () => {
  const content = ["Feature: Login", "", "  Background:", "    Given bg", "", "  Scenario: Good password", "    When a", "",
    "  Scenario: Bad password", "    Then b"].join("\n");
  const shot = (step_text: string, step_line: number, count = 1) => ({ step_text, step_line, hook: null, count });
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content, cases: [
      detailCase(12, { scenario_name: "Good password", line: 6, automated_test_key: KEY }),
      detailCase(13, { scenario_name: "Bad password", line: 9, automated_test_key: KEY2 }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("passed", { result_id: 5, screenshot_steps: [shot("Given bg", 4), shot("When a", 7, 3)] }),
      [KEY2]: result("passed", { result_id: 6 }),
    } })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  const button = await within(cards[0]).findByRole("button", { name: "Screenshots for this step (3)" });
  expect(button.closest(".gk-line")).toHaveTextContent("When a");
  expect(within(cards[0]).getByRole("button", { name: "Screenshots of TC-12 (1)" })).toBeInTheDocument();
  expect(within(screen.getByLabelText("Feature")).queryByRole("button")).toBeNull();
  expect(within(cards[1]).queryByRole("button", { name: /^Screenshots/ })).toBeNull();
});

test("each card's Screenshots link names its case, so a screen reader's list of them has no duplicates", async () => {
  const content = ["Feature: Login", "", "  Background:", "    Given bg", "", "  Scenario: Good password", "    When a", "",
    "  Scenario: Bad password", "    Then b"].join("\n");
  const shot = (count: number) => ({ step_text: "Given bg", step_line: 4, hook: null, count });
  server.use(
    http.get(`${P}/features/detail`, () => HttpResponse.json({ ...DETAIL, content, cases: [
      detailCase(12, { scenario_name: "Good password", line: 6, automated_test_key: KEY }),
      detailCase(13, { scenario_name: "Bad password", line: 9, automated_test_key: KEY2 }),
    ] })),
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("passed", { result_id: 5, screenshot_steps: [shot(1)] }),
      [KEY2]: result("passed", { result_id: 6, screenshot_steps: [shot(2)] }),
    } })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  expect(await within(cards[0]).findByRole("button", { name: "Screenshots of TC-12 (1)" })).toHaveTextContent("Screenshots");
  expect(within(cards[1]).getByRole("button", { name: "Screenshots of TC-13 (2)" })).toBeInTheDocument();
  const names = screen.getAllByRole("button", { name: /^Screenshots of/ }).map((b) => b.getAttribute("aria-label"));
  expect(new Set(names).size).toBe(names.length);
});

test("on a failed line with screenshots, Tab goes line, camera, then the tip; Shift+Tab comes back the same way", async () => {
  server.use(
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("failed", { message: "boom", result_id: 5, failed_step: { text: 'Given I type "secret"', line: 5 },
        screenshot_steps: [{ step_text: 'Given I type "secret"', step_line: 5, hook: "after", count: 2 }] }),
    } })),
  );
  renderAt();
  const camera = await screen.findByRole("button", { name: "Screenshots for this step (2)" });
  const line = camera.closest(".gk-failed") as HTMLElement;
  act(() => line.focus());
  const tip = await screen.findByRole("tooltip");
  await userEvent.tab();
  expect(document.activeElement).toBe(camera);
  await userEvent.tab();
  expect(document.activeElement).toBe(within(tip).getByRole("link", { name: "Open run" }));
  await userEvent.tab({ shift: true });
  expect(document.activeElement).toBe(camera);
});

test("a scenario card shows a Trace button naming its case, only when the result has traces", async () => {
  server.use(
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("passed", { result_id: 77, trace_count: 2 }),
    } })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  expect(await within(cards[0]).findByRole("button", { name: "Open trace 2 of 2 for TC-12 in a new tab" })).toBeInTheDocument();
  expect(within(cards[0]).getByRole("button", { name: "Download traces for TC-12" })).toBeInTheDocument();
  expect(within(cards[1]).queryByRole("button", { name: /(Open|Download) trace/ })).toBeNull();
  expect(screen.queryByText(/playwright show-trace/i)).toBeNull();
});
