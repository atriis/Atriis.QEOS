import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import SuitesPage from "./SuitesPage";
import SuiteDetailPage from "./SuiteDetailPage";

const P = "/api/v1/projects/42";
const TARGET = { available: true, configured: true, provider: "github", repo: "atriis/Atriis.Test.Automation.OBT", workflow: "qeos-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: null, updated_at: "2026-10-07T10:00:00Z", last_change: null };

const repoSuite = (id: number, name: string, extra: object = {}) => ({
  id, name, description: null, case_count: 3, created_at: "2026-10-06T10:00:00Z", updated_at: null,
  origin: "repository", workflow: "suite-flights.yml", group_name: "Flights", external_id: "flights-amadeus-non-booking",
  shard: null, test_paths: ["tests/features/flights/amadeus"], source_repo: "atriis/Atriis.Test.Automation.OBT", ...extra,
});
const manualSuite = (id: number, name: string) => ({
  id, name, description: null, case_count: 1, created_at: "2026-10-06T10:00:00Z", updated_at: null,
  origin: "manual", workflow: null, group_name: null, external_id: null, shard: null, test_paths: null, source_repo: null,
});
const sc = (n: number) => ({ number: n, key: `TC-${n}`, title: `Case ${n}`, status: "draft", priority: "medium", labels: [], automated_test_key: null, source_path: "a.feature" });

const runRequest = (extra: object = {}) => ({
  id: 9, requested_by: 7, requested_at: new Date().toISOString(), selection: [], case_count: 0, suite_id: 2,
  status: "queued", conclusion: null, github_run_id: 501, github_run_url: "https://github.com/acme/obt/actions/runs/501",
  stopped_by: null, stopped_at: null, error: null, checked_at: null, refreshing: true, skipped_manual: 0,
  workflow: "suite-flights.yml", ...extra,
});

beforeEach(() => {
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/ci-target`, () => HttpResponse.json(TARGET)),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 0, items: [] })),
    http.get(`${P}/suites`, () => HttpResponse.json([
      manualSuite(1, "Smoke"), repoSuite(2, "Amadeus non-booking"),
      repoSuite(3, "Hotels basic", { workflow: "suite-hotels.yml", group_name: "Hotels", external_id: "hotels-basic" }),
    ])),
  );
});

function renderAt(url: string) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/suites" element={<SuitesPage />} />
          <Route path="/projects/:projectId/suites/:suiteId" element={<SuiteDetailPage />} />
          <Route path="/projects/:projectId/settings" element={<p>Settings page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The buttons render before the role, the target and the active runs are known; they come on when those arrive
async function ready(name: string) {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

function postCapture() {
  const sent: unknown[] = [];
  server.use(http.post(`${P}/run-requests`, async ({ request }) => { sent.push(await request.json()); return HttpResponse.json(runRequest(), { status: 201 }); }));
  return sent;
}

test("each repository suite row has Run and each group Run all; hand-made suites are left to their page", async () => {
  renderAt("/projects/42/suites");
  await ready("Run Amadeus non-booking");
  expect(screen.getByRole("button", { name: "Run Hotels basic" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run all Flights" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run all Hotels" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /run.*smoke/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /run all made in qeos/i })).not.toBeInTheDocument();
});

test("Run on a suite row says what it starts, then sends the suite id", async () => {
  const sent = postCapture();
  renderAt("/projects/42/suites");
  await userEvent.click(await ready("Run Amadeus non-booking"));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Starts suite-flights.yml for flights-amadeus-non-booking on GitHub.")).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual([{ suite_id: 2 }]));
});

test("Run all sends the workflow group", async () => {
  const sent = postCapture();
  renderAt("/projects/42/suites");
  await userEvent.click(await ready("Run all Flights"));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Starts suite-flights.yml for all its suites.")).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual([{ workflow_group: "suite-flights.yml" }]));
});

test("two workflows with the same name stay two groups, and Run all sends each one's file", async () => {
  server.use(http.get(`${P}/suites`, () => HttpResponse.json([
    repoSuite(2, "Amadeus non-booking"),
    repoSuite(3, "Flights smoke", { workflow: "suite-flights-smoke.yml", external_id: "flights-smoke" }),
  ])));
  const sent = postCapture();
  renderAt("/projects/42/suites");
  await ready("Run all Flights (suite-flights-smoke.yml)");
  expect(screen.getAllByRole("heading", { level: 2, name: /^Flights/ })).toHaveLength(2);
  expect(screen.getByRole("region", { name: "Flights (suite-flights.yml) suites" })).toHaveTextContent("Amadeus non-booking");
  expect(screen.getByRole("region", { name: "Flights (suite-flights-smoke.yml) suites" })).toHaveTextContent("Flights smoke");
  await userEvent.click(screen.getByRole("button", { name: "Run all Flights (suite-flights-smoke.yml)" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual([{ workflow_group: "suite-flights-smoke.yml" }]));
});

test("a suite with no imported cases still runs, and says the workflow decides", async () => {
  server.use(http.get(`${P}/suites`, () => HttpResponse.json([repoSuite(2, "Amadeus non-booking", { case_count: 0 })])));
  renderAt("/projects/42/suites");
  await userEvent.click(await ready("Run Amadeus non-booking"));
  expect(within(screen.getByRole("dialog")).getByText(
    "QEOS has no imported cases for this suite; the workflow runs its folders as configured.")).toBeInTheDocument();
});

test("the repository suite page has Run with the same dialog", async () => {
  const sent = postCapture();
  server.use(http.get(`${P}/suites/2`, () => HttpResponse.json({ ...repoSuite(2, "Amadeus non-booking"), cases: [sc(1), sc(2)] })));
  renderAt("/projects/42/suites/2");
  await userEvent.click(await ready("Run Amadeus non-booking"));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Starts suite-flights.yml for flights-amadeus-non-booking on GitHub.")).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual([{ suite_id: 2 }]));
});

test("a run active on one workflow blocks only that workflow", async () => {
  server.use(http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 1, items: [runRequest()] })));
  renderAt("/projects/42/suites");
  await ready("Run Hotels basic"); // loaded: the gates now know the active run
  expect(screen.getByRole("button", { name: "Run all Hotels" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Run Amadeus non-booking" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Run all Flights" })).toBeDisabled();
});

test("a manual suite is held back by the CI target's workflow, not by a repository one", async () => {
  server.use(
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 1, items: [runRequest()] })),
    http.get(`${P}/suites/1`, () => HttpResponse.json({ ...manualSuite(1, "Smoke"), cases: [sc(1)] })),
  );
  renderAt("/projects/42/suites/1");
  await ready("Run suite");
});

test("a source repository other than the CI target's disables Run and points to Project Settings", async () => {
  server.use(http.get(`${P}/suites`, () => HttpResponse.json([repoSuite(2, "Amadeus non-booking", { source_repo: "other/Repo" })])));
  renderAt("/projects/42/suites");
  const run = await screen.findByRole("button", { name: "Run Amadeus non-booking" });
  await waitFor(() => expect(run).toBeDisabled());
  expect(screen.getAllByRole("link", { name: "Set up Run from QEOS in Project Settings for other/Repo" })[0])
    .toHaveAttribute("href", "/projects/42/settings");
});

test("the repository is compared without regard to case, and an unknown one is left to the server", async () => {
  server.use(http.get(`${P}/suites`, () => HttpResponse.json([
    repoSuite(2, "Amadeus non-booking", { source_repo: "ATRIIS/atriis.test.automation.obt" }),
    repoSuite(4, "Other", { source_repo: null, external_id: "x" }),
  ])));
  renderAt("/projects/42/suites");
  await ready("Run Amadeus non-booking");
  await ready("Run Other");
});

test("workflow_busy shows its message and a View on GitHub link", async () => {
  server.use(http.post(`${P}/run-requests`, () => HttpResponse.json({ detail: {
    code: "workflow_busy", message: "Flights is already running on GitHub (started 10:02). Try again when it finishes.",
    run_url: "https://github.com/acme/obt/actions/runs/77" } }, { status: 409 })));
  renderAt("/projects/42/suites");
  await userEvent.click(await ready("Run all Flights"));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Run" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Flights is already running on GitHub (started 10:02). Try again when it finishes.");
  expect(within(alert).getByRole("link", { name: "View on GitHub" })).toHaveAttribute("href", "https://github.com/acme/obt/actions/runs/77");
});

test("a repository_mismatch refusal disables Run with its message and a link to Project Settings", async () => {
  server.use(http.post(`${P}/run-requests`, () => HttpResponse.json({ detail: {
    code: "repository_mismatch", message: "Set up Run from QEOS in Project Settings for acme/Other" } }, { status: 409 })));
  renderAt("/projects/42/suites");
  const run = await ready("Run all Flights");
  await userEvent.click(run);
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Run" }));
  const link = await screen.findByRole("link", { name: "Set up Run from QEOS in Project Settings for acme/Other" });
  expect(link).toHaveAttribute("href", "/projects/42/settings");
  expect(run).toBeDisabled();
});

test("github_unavailable shows its message with Retry, which asks again", async () => {
  let posts = 0;
  server.use(http.post(`${P}/run-requests`, () => {
    posts += 1;
    if (posts === 1) return HttpResponse.json({ detail: { code: "github_unavailable",
      message: "GitHub could not be asked whether Flights is running; try again." } }, { status: 503 });
    return HttpResponse.json(runRequest(), { status: 201 });
  }));
  renderAt("/projects/42/suites");
  await userEvent.click(await ready("Run all Flights"));
  const dialog = screen.getByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  const alert = await within(dialog).findByRole("alert");
  expect(alert).toHaveTextContent("GitHub could not be asked whether Flights is running; try again.");
  await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(posts).toBe(2));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
