import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import FailedSteps from "./FailedSteps";
import { TEXT_GROUPED_NOTE } from "../lib/failedSteps";

const P = "/api/v1/projects/42";
const SEARCH = "a1b2c3d4e5f60718";
const LOGIN = "0f0f0f0f0f0f0f0f";
const STEPS = { steps: [
  { key: SEARCH, by: "definition", pattern: "When I search {…}", definition: "steps/search.js:12", cases: 3,
    errors: [
      { shape: "Invalid city '…'", example: "Invalid city 'Lisb0n'", cases: 2, tests: [
        { test_key: "k-lisbon", name: "by city Lisbon", text: "When I search Lisb0n" },
        { test_key: "k-porto", name: "by city Porto", text: "When I search P0rto" }] },
      { shape: "", example: null, cases: 1, tests: [{ test_key: "k-faro", name: "by city Faro", text: "When I search Faro" }],
        more: 4 }],
    since: { run_id: 58, started_at: "2026-10-14T09:00:00Z", runs: 4, capped: false },
    last_passed: { run_id: 57, started_at: "2026-10-13T09:00:00Z" } },
  { key: LOGIN, by: "text", pattern: "Given I log in", cases: 1,
    errors: [{ shape: "boom", example: "boom", cases: 1, tests: [{ test_key: "k-login", name: "login", text: "Given I log in" }] }],
    since: { run_id: 61, started_at: "2026-10-14T12:00:00Z", runs: 1, capped: false } },
] };

let searches: { test_keys: string[] }[] = [];
let asked = 0;
function setup(answer: object = STEPS, status = 200) {
  searches = [];
  asked = 0;
  server.use(
    http.get(`${P}/runs/61/failed-steps`, () => {
      asked += 1;
      return status === 200 ? HttpResponse.json(answer) : HttpResponse.json({ detail: "boom" }, { status });
    }),
    http.post(`${P}/cases/search`, async ({ request }) => {
      searches.push(await request.json() as { test_keys: string[] });
      return HttpResponse.json({ total: 3, items: [
        { number: 14, automated_test_key: "k-lisbon" }, { number: 12, automated_test_key: "K-LISBON" },
        { number: 13, automated_test_key: "k-porto" }] });
    }),
  );
}

function renderAt(url = "/projects/42/runs/61") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/runs/:runId" element={<><Link to={`#step-${LOGIN}`}>follow</Link><FailedSteps projectId={42} runId={61} /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
}

const rowOf = (name: string) => screen.getByRole("button", { name }).closest("li") as HTMLElement;

test("one row per step, biggest first, with how wide and since when", async () => {
  setup();
  renderAt();
  expect(await screen.findByRole("heading", { name: "Failed steps" })).toBeInTheDocument();
  const rows = screen.getAllByRole("button", { expanded: false });
  expect(rows.map((b) => b.textContent)).toEqual(["When I search {…}", "Given I log in"]);
  const search = rowOf("When I search {…}");
  expect(search).toHaveTextContent("failed in 3 test cases");
  expect(search).toHaveTextContent(/failing since run #58, .+ \(4 runs\) · last passed in run #57/);
  expect(search).not.toHaveTextContent(TEXT_GROUPED_NOTE);
  const login = rowOf("Given I log in");
  expect(login).toHaveTextContent("failed in 1 test case");
  expect(login).toHaveTextContent("new in this run");
  expect(login).toHaveTextContent(TEXT_GROUPED_NOTE);
});

test("a row opens to its error groups and the test cases with the text they ran", async () => {
  setup();
  renderAt();
  const button = await screen.findByRole("button", { name: "When I search {…}" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "true");
  const panel = document.getElementById(button.getAttribute("aria-controls")!) as HTMLElement;
  expect(panel).toBeVisible();
  expect(within(panel).getByText("Invalid city '…'")).toBeInTheDocument();
  expect(within(panel).getByText("Invalid city 'Lisb0n'")).toBeInTheDocument();
  expect(within(panel).getByText("No error message")).toBeInTheDocument();
  expect(within(panel).getByText("When I search Lisb0n")).toBeInTheDocument();
  expect(within(panel).getByText("and 4 more")).toBeInTheDocument();
  // The lowest linked case number wins, as of this run
  expect(await within(panel).findByRole("link", { name: "by city Lisbon" })).toHaveAttribute("href", "/projects/42/cases/12?run=61");
  expect(await within(panel).findByRole("link", { name: "by city Porto" })).toHaveAttribute("href", "/projects/42/cases/13?run=61");
  expect(searches[0].test_keys).toEqual(["k-faro", "k-lisbon", "k-login", "k-porto"]);
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "false");
});

test("a test without a case links to its history", async () => {
  setup();
  renderAt();
  await userEvent.click(await screen.findByRole("button", { name: "When I search {…}" }));
  expect(await screen.findByRole("link", { name: "by city Faro" })).toHaveAttribute("href", "/projects/42/tests/k-faro");
});

test("a link to a step's anchor opens that row", async () => {
  setup();
  renderAt(`/projects/42/runs/61#step-${LOGIN}`);
  expect(await screen.findByRole("button", { name: "Given I log in" })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "When I search {…}" })).toHaveAttribute("aria-expanded", "false");
  expect(document.getElementById(`step-${LOGIN}`)).not.toBeNull();
});

test("a run without failed steps shows nothing", async () => {
  setup({ steps: [] });
  const qc = renderAt();
  await waitFor(() => expect(asked).toBe(1));
  await waitFor(() => expect(qc.getQueryState(["failed-steps", 42, 61])?.status).toBe("success"));
  expect(screen.queryByRole("heading", { name: "Failed steps" })).toBeNull();
});

test("a failed request says so with Retry inside the section", async () => {
  setup(STEPS, 500);
  renderAt();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Failed steps" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
});

test("following a step's link again reopens its row after it was collapsed", async () => {
  setup();
  renderAt(`/projects/42/runs/61#step-${LOGIN}`);
  const button = await screen.findByRole("button", { name: "Given I log in" });
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(screen.getByRole("link", { name: "follow" }));
  await waitFor(() => expect(button).toHaveAttribute("aria-expanded", "true"));
});

test("the stylesheet keeps a collapsed panel hidden (an author display would override [hidden])", () => {
  const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");
  expect(css).toMatch(/\.step-errors\[hidden\]\s*\{\s*display:\s*none/);
});
