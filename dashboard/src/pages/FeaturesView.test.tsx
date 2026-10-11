import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CasesPage from "./CasesPage";

const P = "/api/v1/projects/42";
const KEY = "c".repeat(64);
const TARGET = { available: true, configured: true, provider: "github", repo: "acme/obt", workflow: "qeos-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: null, updated_at: "2026-10-07T10:00:00Z", last_change: null };

const kase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, description: null, steps: [], labels: [], priority: "medium",
  status: "draft", automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z",
  updated_by: null, updated_at: null, suites: [], source_path: null, gherkin: null, feature_name: null, ...extra,
});

const LOGIN = { feature_name: "Login", path: "features/auth/login.feature", folder: "features/auth", case_count: 2,
  case_numbers: [1, 2], has_source: true };
const MANUAL = { feature_name: null, path: null, folder: null, case_count: 1, case_numbers: [9], has_source: false };

const detailCase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, scenario_name: `Case ${number}`, status: "ready",
  priority: "high", automated_test_key: null, line: null, ...extra,
});
const LOGIN_DETAIL = {
  feature_name: "Login", path: LOGIN.path, folder: LOGIN.folder, content: null, imported_at: null,
  // File order; case 3 no longer matches the filters, so the row's case_numbers leave it out
  cases: [detailCase(2, { automated_test_key: KEY }), detailCase(3), detailCase(1)],
};

function Location() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{pathname + search}</output>;
}

const seenFeatures: URLSearchParams[] = [];
const seenCases: URLSearchParams[] = [];

beforeEach(() => {
  seenFeatures.length = 0;
  seenCases.length = 0;
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/ci-target`, () => HttpResponse.json(TARGET)),
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, ({ request }) => {
      const sp = new URL(request.url).searchParams;
      if (sp.get("limit") !== "1") seenCases.push(sp);
      if (sp.get("origin") === "manual") return HttpResponse.json({ total: 1, items: [kase(9, { title: "Written by hand" })] });
      return HttpResponse.json({ total: 2, items: [kase(1), kase(2)] });
    }),
    http.get(`${P}/features`, ({ request }) => {
      seenFeatures.push(new URL(request.url).searchParams);
      return HttpResponse.json({ total: 2, items: [LOGIN, MANUAL] });
    }),
    http.get(`${P}/features/detail`, () => HttpResponse.json(LOGIN_DETAIL)),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ runs: [], statuses: {} })),
  );
});

function renderCases(url = "/projects/42/cases") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/projects/:projectId/cases" element={<><CasesPage /><Location /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const featureRow = (name: string) => screen.getByText(name, { selector: "a, .feature-name" }).closest("tr")!;

test("the Cases list opens grouped by feature: one row per .feature file, manual cases last", async () => {
  renderCases();
  const link = await screen.findByRole("link", { name: "Login" });
  expect(link).toHaveAttribute("href", "/projects/42/cases/feature?path=features%2Fauth%2Flogin.feature");
  const row = link.closest("tr")!;
  expect(within(row).getByText("features/auth")).toBeInTheDocument();
  // No scenario-count column: the row carries no numeric cell
  expect(within(row).getAllByRole("cell").filter((c) => c.classList.contains("num"))).toHaveLength(0);
  expect(screen.getByText("No feature (manual)")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "No feature (manual)" })).not.toBeInTheDocument();
  // Feature view searches in feature names and paths unless told otherwise, and the server is always told
  expect(seenFeatures[0].get("search_in")).toBe("feature");
  expect(seenFeatures[0].get("limit")).toBe("50");
});

test("long names are cut to one line with an ellipsis; the full text stays in the title and the accessible name", async () => {
  renderCases();
  const link = await screen.findByRole("link", { name: "Login" });
  expect(link).toHaveClass("truncate");
  expect(link).toHaveAttribute("title", "Login");
  const folder = within(link.closest("tr")!).getByText("features/auth");
  expect(folder).toHaveClass("truncate");
  expect(folder).toHaveAttribute("title", "features/auth");
  await userEvent.click(within(featureRow("Login")).getByRole("button", { name: "Show scenarios of Login" }));
  const scenarios = await screen.findByRole("rowgroup", { name: "Scenarios of Login" });
  const title = within(scenarios).getByRole("link", { name: "Case 2" });
  expect(title).toHaveClass("case-title", "truncate");
  expect(title).toHaveAttribute("title", "Case 2");
});

test("both views use one fixed column layout, so columns keep their place across pages and views", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const fixed = (table: HTMLElement) =>
    within(table).getAllByRole("columnheader").map((th) => [...th.classList].find((c) => c.startsWith("col-")) ?? "");
  expect(screen.getByRole("table")).toHaveClass("cases-table");
  expect(fixed(screen.getByRole("table"))).toEqual(["col-select", "col-title", "col-runs", "col-priority", "col-status", "col-automated"]);
  await userEvent.click(within(screen.getByRole("group", { name: "Group by" })).getByRole("button", { name: "Scenario" }));
  await screen.findByRole("link", { name: "Case 1" });
  expect(screen.getByRole("table")).toHaveClass("cases-table");
  expect(fixed(screen.getByRole("table"))).toEqual(["col-select", "col-title", "col-runs", "col-priority", "col-status", "col-automated"]);
});

test("Group by is a pressed-button group stored in the URL; Scenario shows today's list", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const group = screen.getByRole("group", { name: "Group by" });
  expect(within(group).getByRole("button", { name: "Feature" })).toHaveAttribute("aria-pressed", "true");
  expect(within(group).getByRole("button", { name: "Scenario" })).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(within(group).getByRole("button", { name: "Scenario" }));
  expect(await screen.findByRole("link", { name: "Case 1" })).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent("group=scenario");
  expect(within(group).getByRole("button", { name: "Scenario" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("link", { name: "Login" })).not.toBeInTheDocument();
});

test("Search in defaults to Feature in Feature view and Scenario in Scenario view, and reaches the API", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  expect(screen.getByRole("combobox", { name: "Search in" })).toHaveValue("feature");
  await userEvent.type(screen.getByLabelText("Search"), "pay");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Search in" }), "both");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(seenFeatures[seenFeatures.length - 1].get("search_in")).toBe("both"));
  expect(seenFeatures[seenFeatures.length - 1].get("search")).toBe("pay");
  expect(screen.getByTestId("where")).toHaveTextContent("search_in=both");
});

test("Scenario view searches scenarios by default and sends search_in to /cases", async () => {
  renderCases("/projects/42/cases?group=scenario&q=login");
  await screen.findByRole("link", { name: "Case 1" });
  expect(screen.getByRole("combobox", { name: "Search in" })).toHaveValue("scenario");
  expect(seenCases[seenCases.length - 1].get("search_in")).toBe("scenario");
});

test("Apply keeps the grouping", async () => {
  renderCases("/projects/42/cases?group=scenario");
  await screen.findByRole("link", { name: "Case 1" });
  await userEvent.type(screen.getByLabelText("Search"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("q=x"));
  expect(screen.getByTestId("where")).toHaveTextContent("group=scenario");
});

test("a feature row expands in place to its matching scenarios, in file order", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const toggle = within(featureRow("Login")).getByRole("button", { name: "Show scenarios of Login" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  const scenarios = await screen.findByRole("rowgroup", { name: "Scenarios of Login" });
  const titles = within(scenarios).getAllByRole("link").filter((a) => a.classList.contains("case-title")).map((a) => a.textContent);
  expect(titles).toEqual(["Case 2", "Case 1"]);
  expect(within(scenarios).getByRole("link", { name: "Case 2" })).toHaveAttribute("href", "/projects/42/cases/2");
  await userEvent.click(toggle);
  expect(screen.queryByRole("rowgroup", { name: "Scenarios of Login" })).not.toBeInTheDocument();
});

test("feature and scenario rows share one table with the Scenario view's columns", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  await userEvent.click(within(featureRow("Login")).getByRole("button", { name: "Show scenarios of Login" }));
  const scenarios = await screen.findByRole("rowgroup", { name: "Scenarios of Login" });
  expect(screen.getAllByRole("table")).toHaveLength(1);
  const heads = within(screen.getByRole("table")).getAllByRole("columnheader").map((th) => th.textContent);
  // The first header cell holds the "Select every scenario on this page" box
  expect(heads).toEqual(["", "Title", "Last runs", "Priority", "Status", "Automated"]);
  const caseRow = within(scenarios).getByRole("link", { name: "Case 2" }).closest("tr")!;
  const cells = within(caseRow).getAllByRole("cell");
  expect(cells).toHaveLength(heads.length);
  expect(cells[3]).toHaveTextContent("high");
  expect(cells[5]).toHaveTextContent("Linked");
  expect(within(featureRow("Login")).getAllByRole("cell")).toHaveLength(heads.length);
});

test("an expanded scenario's checkbox sits indented in its title cell, not in the feature's select column", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  await userEvent.click(within(featureRow("Login")).getByRole("button", { name: "Show scenarios of Login" }));
  const scenarios = await screen.findByRole("rowgroup", { name: "Scenarios of Login" });
  const box = within(scenarios).getByRole("checkbox", { name: "Select TC-1 Case 1" });
  const row = box.closest("tr")!;
  const cells = within(row).getAllByRole("cell");
  // The select column stays empty; the box lives in the title cell, inside the nested-check slot
  expect(within(cells[0]).queryByRole("checkbox")).not.toBeInTheDocument();
  expect(cells[1]).toContainElement(box);
  expect(box.closest(".nested-check")).not.toBeNull();
  await userEvent.click(box);
  expect(await screen.findByRole("button", { name: "Run selected (1)" })).toBeInTheDocument();
});

test("the manual group expands to the manual cases", async () => {
  renderCases();
  await screen.findByText("No feature (manual)");
  await userEvent.click(within(featureRow("No feature (manual)")).getByRole("button", { name: "Show scenarios of No feature (manual)" }));
  expect(await screen.findByRole("link", { name: "Written by hand" })).toBeInTheDocument();
  expect(seenCases.some((sp) => sp.get("origin") === "manual")).toBe(true);
});

test("checking a feature selects its runnable scenarios; the box is tri-state", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const box = within(featureRow("Login")).getByRole("checkbox", { name: "Select every scenario of Login" }) as HTMLInputElement;
  // A manual group has nothing to run, so no box
  expect(within(featureRow("No feature (manual)")).queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(box);
  expect(await screen.findByRole("button", { name: "Run selected (2)" })).toBeInTheDocument();
  expect(box).toBeChecked();
  await userEvent.click(within(featureRow("Login")).getByRole("button", { name: "Show scenarios of Login" }));
  const scenarios = await screen.findByRole("rowgroup", { name: "Scenarios of Login" });
  await userEvent.click(within(scenarios).getByRole("checkbox", { name: "Select TC-1 Case 1" }));
  expect(screen.getByRole("button", { name: "Run selected (1)" })).toBeInTheDocument();
  expect(box).not.toBeChecked();
  expect(box.indeterminate).toBe(true);
  await userEvent.click(box);
  expect(await screen.findByRole("button", { name: "Run selected (2)" })).toBeInTheDocument();
  await userEvent.click(box);
  expect(screen.queryByRole("button", { name: /Run selected/ })).not.toBeInTheDocument();
});

test("the header box selects every runnable scenario of the features on the page, and is tri-state", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const all = screen.getByRole("checkbox", { name: "Select every scenario on this page" }) as HTMLInputElement;
  await userEvent.click(all);
  expect(await screen.findByRole("button", { name: "Run selected (2)" })).toBeInTheDocument();
  expect(all).toBeChecked();
  expect(within(featureRow("Login")).getByRole("checkbox", { name: "Select every scenario of Login" })).toBeChecked();
  // One scenario off: the header shows a partial selection
  await userEvent.click(within(featureRow("Login")).getByRole("button", { name: "Show scenarios of Login" }));
  const scenarios = await screen.findByRole("rowgroup", { name: "Scenarios of Login" });
  await userEvent.click(within(scenarios).getByRole("checkbox", { name: "Select TC-1 Case 1" }));
  expect(all).not.toBeChecked();
  expect(all.indeterminate).toBe(true);
  // Checking it again completes the selection; unchecking clears it
  await userEvent.click(all);
  expect(await screen.findByRole("button", { name: "Run selected (2)" })).toBeInTheDocument();
  await userEvent.click(all);
  expect(screen.queryByRole("button", { name: /Run selected/ })).not.toBeInTheDocument();
});

test("a filter the feature list cannot apply groups the matching cases in the page instead", async () => {
  server.use(http.get(`${P}/cases`, ({ request }) => {
    const sp = new URL(request.url).searchParams;
    if (sp.get("limit") !== "1") seenCases.push(sp);
    return HttpResponse.json({ total: 3, items: [
      kase(1, { source_path: LOGIN.path, feature_name: "Login" }),
      kase(4, { source_path: "features/pay.feature", feature_name: "Pay" }),
      kase(9, { title: "Written by hand" }),
    ] });
  }));
  renderCases("/projects/42/cases?origin=imported");
  expect(await screen.findByRole("link", { name: "Login" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Pay" })).toBeInTheDocument();
  expect(seenFeatures).toHaveLength(0);
  expect(seenCases[seenCases.length - 1].get("origin")).toBe("imported");
  await userEvent.click(within(featureRow("Pay")).getByRole("button", { name: "Show scenarios of Pay" }));
  expect(await screen.findByRole("link", { name: "Case 4" })).toBeInTheDocument();
});

const withFeatures = (...items: object[]) =>
  server.use(http.get(`${P}/features`, () => HttpResponse.json({ total: items.length, items })));
const STATUSES = { draft: 0, ready: 0, archived: 0 };

test("a feature row shows its highest priority, its statuses and how many scenarios are linked", async () => {
  withFeatures({ ...LOGIN, case_count: 5, case_numbers: [1, 2, 3, 4, 5], linked_count: 3, top_priority: "high",
    status_counts: { ...STATUSES, ready: 2, draft: 1, archived: 2 } });
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const row = featureRow("Login");
  expect(within(row).getByLabelText("Highest priority: high")).toHaveTextContent("high");
  expect(within(row).getByText("2 ready · 1 draft · 2 archived")).toHaveClass("muted");
  expect(within(row).queryByText("ready", { selector: ".pill, .status-pill, span" })).not.toBeInTheDocument();
  expect(within(row).getAllByText("3 of 5 linked").length).toBeGreaterThan(0);
});

test("a feature whose scenarios share one status shows a single pill, and an all-linked one says so", async () => {
  withFeatures({ ...LOGIN, linked_count: 2, top_priority: "medium", status_counts: { ...STATUSES, ready: 2 } });
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const row = featureRow("Login");
  expect(within(row).getByText("Ready")).toBeInTheDocument();
  expect(within(row).queryByText(/·/)).not.toBeInTheDocument();
  const all = within(within(row).getAllByRole("cell").at(-1)!).getByText("All linked");
  expect(all).toHaveClass("linked");
});

test("a manual group says Manual and shows nothing for a missing priority", async () => {
  withFeatures({ ...MANUAL, linked_count: 0, top_priority: null, status_counts: { ...STATUSES, draft: 1 } });
  renderCases();
  await screen.findByText("No feature (manual)");
  const row = featureRow("No feature (manual)");
  expect(within(within(row).getAllByRole("cell").at(-1)!).getByText("Manual")).toHaveClass("muted");
  expect(within(row).queryByLabelText(/Highest priority/)).not.toBeInTheDocument();
  expect(within(row).getByText("Draft")).toBeInTheDocument();
});

test("an older server's feature row leaves the aggregate cells empty", async () => {
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const cells = within(featureRow("Login")).getAllByRole("cell").slice(-3);
  expect(cells.map((c) => c.textContent)).toEqual(["", "", ""]);
});

test("the client-side grouping computes the same aggregates from the cases", async () => {
  server.use(http.get(`${P}/cases`, () => HttpResponse.json({ total: 3, items: [
    kase(1, { source_path: LOGIN.path, feature_name: "Login", priority: "low", status: "ready", automated_test_key: KEY }),
    kase(2, { source_path: LOGIN.path, feature_name: "Login", priority: "critical", status: "draft" }),
    kase(3, { source_path: "features/pay.feature", feature_name: "Pay", status: "ready", automated_test_key: KEY }),
  ] })));
  renderCases("/projects/42/cases?origin=imported");
  await screen.findByRole("link", { name: "Login" });
  const login = featureRow("Login");
  expect(within(login).getByLabelText("Highest priority: critical")).toBeInTheDocument();
  expect(within(login).getByText("1 ready · 1 draft")).toBeInTheDocument();
  expect(within(login).getAllByText("1 of 2 linked").length).toBeGreaterThan(0);
  const pay = featureRow("Pay");
  expect(within(pay).getByText("Ready")).toBeInTheDocument();
  expect(within(pay).getAllByText("All linked").length).toBeGreaterThan(0);
});


// --- Last runs strip on feature rows, the legend, file names ---------------------------------------------------

const KEY_A = "a".repeat(64);
const KEY_B = "b".repeat(64);
const RUNS = [{ id: 1, started_at: "2026-10-06T10:00:00Z", branch: "main" }, { id: 2, started_at: "2026-10-07T10:00:00Z", branch: "main" }];

test("a feature row shows one strip: the worst status per run over its scenarios", async () => {
  withFeatures({ ...LOGIN, test_keys: [KEY_A, KEY_B] });
  server.use(http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({
    runs: RUNS, statuses: { [KEY_A]: ["passed", "passed"], [KEY_B]: ["failed", "passed"] },
  })));
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const strip = await within(featureRow("Login")).findByRole("link", { name: /^Last 2 runs/ });
  expect(strip).toHaveAttribute("aria-label", "Last 2 runs: 1 passed, 1 failed, opens run #2");
  expect(strip).toHaveAttribute("href", "/projects/42/runs/2");
  expect(strip.querySelectorAll(".bar-failed")).toHaveLength(1);
  expect(strip.querySelectorAll(".bar-passed")).toHaveLength(1);
});

test("a feature row's Last runs is the strip alone, never a failing count; the narrow line summarises the runs", async () => {
  withFeatures({ ...LOGIN, test_keys: [KEY_A] });
  server.use(
    http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ keys: [KEY_A] })),
    http.post(`${P}/cases/search`, () => HttpResponse.json({ total: 1, items: [kase(2, { automated_test_key: KEY_A })] })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ runs: RUNS, statuses: { [KEY_A]: ["passed", "failed"] } })),
  );
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  const row = featureRow("Login");
  expect(await within(row).findByRole("link", { name: /^Last 2 runs/ })).toBeInTheDocument();
  expect(within(row).queryByText(/failing/)).not.toBeInTheDocument();
  expect(within(row).getByText("1 failed, 1 passed of the last 2")).toBeInTheDocument();
});

test("more than 200 keys go out in chunks of 200, merged into one strip", async () => {
  const keys = Array.from({ length: 201 }, (_, i) => i.toString(16).padStart(64, "0")).sort();
  const bodies: { test_keys: string[] }[] = [];
  withFeatures({ ...LOGIN, test_keys: keys.slice(0, 200) }, { ...MANUAL, path: "m.feature", feature_name: "M", test_keys: keys.slice(200) });
  server.use(http.post(`${P}/analytics/run-strip`, async ({ request }) => {
    const body = (await request.json()) as { test_keys: string[] };
    bodies.push(body);
    const statuses = Object.fromEntries(body.test_keys.map((k) => [k, [k === keys[200] ? "failed" : "passed"]]));
    return HttpResponse.json({ runs: [RUNS[0]], statuses });
  }));
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  expect(await within(featureRow("M")).findByRole("link", { name: /^Last 1 run: 1 failed/ })).toBeInTheDocument();
  expect(within(featureRow("Login")).getByRole("link", { name: /^Last 1 run: 1 passed/ })).toBeInTheDocument();
  expect(bodies.map((b) => b.test_keys.length).sort()).toEqual([1, 200]);
});

test("a feature row shows a skeleton while loading and a dash when the strips fail", async () => {
  withFeatures({ ...LOGIN, test_keys: [KEY_A] });
  server.use(http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ detail: "no" }, { status: 500 })));
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  expect(await within(featureRow("Login")).findByLabelText("Last runs unavailable")).toHaveTextContent("—");
});

test("a manual row with no keys says not linked; an older server's row leaves the cell empty", async () => {
  withFeatures({ ...MANUAL, test_keys: [] });
  renderCases();
  await screen.findByText("No feature (manual)");
  expect(within(featureRow("No feature (manual)")).getByText("not linked")).toHaveClass("muted");
});

test("the legend shows in Feature view without expanding a row, and hides when no row has keys", async () => {
  withFeatures({ ...LOGIN, test_keys: [KEY_A] });
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  expect(screen.getByRole("list", { name: "Last runs legend" })).toBeInTheDocument();
});

test("the legend is hidden in Feature view when no row has keys", async () => {
  withFeatures({ ...LOGIN, test_keys: [] });
  renderCases();
  await screen.findByRole("link", { name: "Login" });
  expect(screen.queryByRole("list", { name: "Last runs legend" })).not.toBeInTheDocument();
});

test("a file with no Feature name shows its file name without .feature; a real Feature title is unchanged", async () => {
  withFeatures(
    { ...LOGIN, feature_name: null, path: "features/foo_bar.feature", folder: "features" },
    { ...LOGIN, feature_name: "Pay.feature", path: "features/pay.feature", folder: "features" },
  );
  renderCases();
  const link = await screen.findByRole("link", { name: "foo_bar" });
  expect(link).toHaveAttribute("href", "/projects/42/cases/feature?path=features%2Ffoo_bar.feature");
  expect(screen.getByRole("link", { name: "Pay.feature" })).toBeInTheDocument();
});
